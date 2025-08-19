import os
import time
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
import json
from dotenv import load_dotenv

from aptos_sdk.account import Account
from aptos_sdk.account_address import AccountAddress
from aptos_sdk.async_client import RestClient
from aptos_sdk.transactions import EntryFunction, TransactionArgument, TransactionPayload
from aptos_sdk.bcs import Serializer

# Load environment variables
load_dotenv()

# Debug: Print environment variables (without exposing full private key)
print(f"DEBUG: NODE_URL: {os.getenv('NODE_URL', 'NOT_SET')}")
print(f"DEBUG: PAYER_ADDRESS: {os.getenv('PAYER_ADDRESS', 'NOT_SET')}")
print(f"DEBUG: MODULE_ADDRESS: {os.getenv('MODULE_ADDRESS', 'NOT_SET')}")
print(f"DEBUG: PAYER_PRIVATE_KEY_HEX: {os.getenv('PAYER_PRIVATE_KEY_HEX', 'NOT_SET')[:20]}...")

app = FastAPI(title="Tuition Escrow API", version="1.0.0")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files (for serving the HTML file)
app.mount("/static", StaticFiles(directory="../frontend"), name="static")

# Configuration
NODE_URL = os.getenv("NODE_URL", "https://fullnode.devnet.aptoslabs.com/v1")
PAYER_PRIVATE_KEY_HEX = os.getenv("PAYER_PRIVATE_KEY_HEX")
PAYER_ADDRESS = os.getenv("PAYER_ADDRESS")
MODULE_ADDRESS = os.getenv("MODULE_ADDRESS")

# Initialize Aptos client
client = RestClient(NODE_URL)

async def get_payer_account() -> Account:
    """Get the payer account from private key"""
    if not PAYER_PRIVATE_KEY_HEX:
        raise HTTPException(status_code=500, detail="PAYER_PRIVATE_KEY_HEX not configured")
    
    # Remove prefix if present and clean the private key
    private_key = PAYER_PRIVATE_KEY_HEX.strip()
    print(f"DEBUG: Original private key: {private_key[:20]}...{private_key[-20:]}")
    
    if private_key.startswith("ed25519-priv-"):
        private_key = private_key[14:]  # Remove "ed25519-priv-" prefix
        print(f"DEBUG: After removing prefix: {private_key[:20]}...{private_key[-20:]}")
    
    # Remove any existing 0x prefix and add a clean one
    if private_key.startswith("0x"):
        private_key = private_key[2:]  # Remove existing 0x
        print(f"DEBUG: After removing 0x: {private_key[:20]}...{private_key[-20:]}")
    elif private_key.startswith("x"):  # Handle case where prefix removal left just 'x'
        private_key = private_key[1:]  # Remove the 'x'
        print(f"DEBUG: After removing x: {private_key[:20]}...{private_key[-20:]}")
    
    private_key = "0x" + private_key  # Add clean 0x prefix
    print(f"DEBUG: Final private key: {private_key[:10]}...{private_key[-10:]}")
    
    try:
        return Account.load_key(private_key)
    except Exception as e:
        print(f"DEBUG: Error loading account: {str(e)}")  # Debug line
        raise HTTPException(status_code=500, detail=f"Failed to load account: {str(e)}")

# Pydantic models
class TuitionAgreement(BaseModel):
    total_amount: int = Field(..., description="Total tuition amount in octas")
    num_installments: int = Field(..., description="Number of installments")
    installment_amount: int = Field(..., description="Amount per installment in octas")
    interval_days: int = Field(..., description="Days between installments")
    penalty_rate: int = Field(..., description="Penalty rate per day (basis points)")
    grace_period_days: int = Field(..., description="Grace period before penalties")

class PaymentRequest(BaseModel):
    agreement_id: int = Field(..., description="Agreement ID to pay")

class AgreementSummary(BaseModel):
    id: int
    payer: str
    installment_amount: int
    total_installments: int
    paid_installments: int
    start_time_secs: int
    interval_secs: int
    penalty_bps: int
    grace_period_secs: int
    total_paid: int

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    """Serve the main frontend HTML page"""
    try:
        with open("../frontend/index.html", "r", encoding="utf-8") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Frontend file not found</h1><p>Make sure index.html exists in the frontend folder.</p>")
    except Exception as e:
        return HTMLResponse(content=f"<h1>Error loading frontend</h1><p>{str(e)}</p>")

@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "message": "Tuition Escrow API is running"}

@app.post("/api/agreements", response_model=Dict[str, Any])
async def create_agreement(agreement: TuitionAgreement):
    """Create a new tuition agreement"""
    try:
        payer = get_payer_account()
        
        # Prepare transaction arguments
        def u64_encoder(serializer, value):
            serializer.u64(value)
            return serializer.output()
        
        def address_encoder(serializer, value):
            value.serialize(serializer)
            return serializer.output()
        
        # Convert days to seconds for the contract
        start_time_secs = int(time.time())
        interval_secs = agreement.interval_days * 24 * 60 * 60
        grace_period_secs = agreement.grace_period_days * 24 * 60 * 60
        
        args = [
            TransactionArgument(agreement.installment_amount, u64_encoder),
            TransactionArgument(agreement.num_installments, u64_encoder),
            TransactionArgument(start_time_secs, u64_encoder),
            TransactionArgument(interval_secs, u64_encoder),
            TransactionArgument(agreement.penalty_rate, u64_encoder),
            TransactionArgument(grace_period_secs, u64_encoder),
        ]
        
        # Create transaction payload
        payload = TransactionPayload(
            EntryFunction.natural(
                f"{MODULE_ADDRESS}::tuition_escrow_v2",
                "create_agreement",
                [],
                args
            )
        )
        
        # Submit transaction
        signed_transaction = client.create_bcs_signed_transaction(payer, payload)
        tx_hash = client.submit_bcs_transaction(signed_transaction)
        
        # Wait for transaction
        client.wait_for_transaction(tx_hash)

        # Try to read Store.next_id and compute the created agreement id (next_id - 1)
        created_id: Optional[int] = None
        try:
            store_resource = client.account_resource(
                AccountAddress.from_hex(MODULE_ADDRESS),
                f"{MODULE_ADDRESS}::tuition_escrow_v2::Store",
            )
            if store_resource and isinstance(store_resource, dict):
                data = store_resource.get("data") or {}
                next_id_val = data.get("next_id")
                if next_id_val is not None:
                    created_id = int(next_id_val) - 1
        except Exception:
            created_id = None

        return {
            "success": True,
            "transaction_hash": str(tx_hash),
            "message": "Tuition agreement created successfully",
            "agreement_id": created_id,
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create agreement: {str(e)}")

@app.post("/api/agreements/{agreement_id}/pay", response_model=Dict[str, Any])
async def pay_next_installment(agreement_id: int):
    """Pay the next installment for an agreement"""
    try:
        payer = get_payer_account()
        
        # Prepare transaction arguments
        def u64_encoder(serializer, value):
            serializer.u64(value)
            return serializer.output()
        
        args = [
            TransactionArgument(agreement_id, u64_encoder),
        ]
        
        # Create transaction payload
        payload = TransactionPayload(
            EntryFunction.natural(
                f"{MODULE_ADDRESS}::tuition_escrow_v2",
                "pay_next_installment",
                [],
                args
            )
        )
        
        # Submit transaction
        signed_transaction = client.create_bcs_signed_transaction(payer, payload)
        tx_hash = client.submit_bcs_transaction(signed_transaction)
        
        # Wait for transaction
        client.wait_for_transaction(tx_hash)
        
        return {
            "success": True,
            "transaction_hash": str(tx_hash),
            "message": f"Installment {agreement_id} paid successfully"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to pay installment: {str(e)}")

@app.get("/api/agreements/{agreement_id}", response_model=AgreementSummary)
async def get_agreement_summary(agreement_id: int):
    """Get agreement summary from blockchain"""
    try:
        # Get the Store resource from the module address
        store_resource = client.account_resource(
            AccountAddress.from_hex(MODULE_ADDRESS),
            f"{MODULE_ADDRESS}::tuition_escrow_v2::Store"
        )
        
        if not store_resource:
            raise HTTPException(status_code=404, detail="Store resource not found")
        
        # For now, return a basic structure since we need to parse the resource data
        # In a real implementation, you'd parse the resource data to get agreement details
        return AgreementSummary(
            id=agreement_id,
            payer="0x...",  # Would be extracted from resource
            installment_amount=0,  # Would be extracted from resource
            total_installments=0,    # Would be extracted from resource
            paid_installments=0,     # Would be extracted from resource
            start_time_secs=0,       # Would be extracted from resource
            interval_secs=0,         # Would be extracted from resource
            penalty_bps=0,          # Would be extracted from resource
            grace_period_secs=0,    # Would be extracted from resource
            total_paid=0,          # Would be extracted from resource
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get agreement: {str(e)}")

# ...existing code...

@app.post("/api/agreements", response_model=Dict[str, Any])
async def create_agreement(agreement: TuitionAgreement):
    """Create a new tuition agreement"""
    try:
        payer = await get_payer_account()
        
        # Prepare transaction arguments
        def u64_encoder(serializer, value):
            serializer.u64(value)
            return serializer.output()
        
        def address_encoder(serializer, value):
            value.serialize(serializer)
            return serializer.output()
        
        # Convert days to seconds for the contract
        start_time_secs = int(time.time())
        interval_secs = agreement.interval_days * 24 * 60 * 60
        grace_period_secs = agreement.grace_period_days * 24 * 60 * 60
        
        args = [
            TransactionArgument(agreement.installment_amount, u64_encoder),
            TransactionArgument(agreement.num_installments, u64_encoder),
            TransactionArgument(start_time_secs, u64_encoder),
            TransactionArgument(interval_secs, u64_encoder),
            TransactionArgument(agreement.penalty_rate, u64_encoder),
            TransactionArgument(grace_period_secs, u64_encoder),
        ]
        
        # Create transaction payload
        payload = TransactionPayload(
            EntryFunction.natural(
                f"{MODULE_ADDRESS}::tuition_escrow_v2",
                "create_agreement",
                [],
                args
            )
        )
        
        # Submit transaction
        signed_transaction = await client.create_bcs_signed_transaction(payer, payload)
        tx_hash = await client.submit_bcs_transaction(signed_transaction)
        
        # Wait for transaction
        await client.wait_for_transaction(tx_hash)

        # Try to read Store.next_id and compute the created agreement id (next_id - 1)
        created_id: Optional[int] = None
        try:
            store_resource = await client.account_resource(
                AccountAddress.from_hex(MODULE_ADDRESS),
                f"{MODULE_ADDRESS}::tuition_escrow_v2::Store",
            )
            if store_resource and isinstance(store_resource, dict):
                data = store_resource.get("data") or {}
                next_id_val = data.get("next_id")
                if next_id_val is not None:
                    created_id = int(next_id_val) - 1
        except Exception:
            created_id = None

        return {
            "success": True,
            "transaction_hash": str(tx_hash),
            "message": "Tuition agreement created successfully",
            "agreement_id": created_id,
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create agreement: {str(e)}")

@app.post("/api/agreements/{agreement_id}/pay", response_model=Dict[str, Any])
async def pay_next_installment(agreement_id: int):
    """Pay the next installment for an agreement"""
    try:
        payer = await get_payer_account()
        
        # Prepare transaction arguments
        def u64_encoder(serializer, value):
            serializer.u64(value)
            return serializer.output()
        
        args = [
            TransactionArgument(agreement_id, u64_encoder),
        ]
        
        # Create transaction payload
        payload = TransactionPayload(
            EntryFunction.natural(
                f"{MODULE_ADDRESS}::tuition_escrow_v2",
                "pay_next_installment",
                [],
                args
            )
        )
        
        # Submit transaction
        signed_transaction = await client.create_bcs_signed_transaction(payer, payload)
        tx_hash = await client.submit_bcs_transaction(signed_transaction)
        
        # Wait for transaction
        await client.wait_for_transaction(tx_hash)
        
        return {
            "success": True,
            "transaction_hash": str(tx_hash),
            "message": f"Installment {agreement_id} paid successfully"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to pay installment: {str(e)}")

@app.get("/api/agreements/{agreement_id}", response_model=AgreementSummary)
async def get_agreement_summary(agreement_id: int):
    """Get agreement summary from blockchain"""
    try:
        # Get the Store resource from the module address
        store_resource = await client.account_resource(
            AccountAddress.from_hex(MODULE_ADDRESS),
            f"{MODULE_ADDRESS}::tuition_escrow_v2::Store"
        )
        
        if not store_resource:
            raise HTTPException(status_code=404, detail="Store resource not found")
        
        # For now, return a basic structure since we need to parse the resource data
        # In a real implementation, you'd parse the resource data to get agreement details
        return AgreementSummary(
            id=agreement_id,
            payer="0x...",  # Would be extracted from resource
            installment_amount=0,  # Would be extracted from resource
            total_installments=0,    # Would be extracted from resource
            paid_installments=0,     # Would be extracted from resource
            start_time_secs=0,       # Would be extracted from resource
            interval_secs=0,         # Would be extracted from resource
            penalty_bps=0,          # Would be extracted from resource
            grace_period_secs=0,    # Would be extracted from resource
            total_paid=0,          # Would be extracted from resource
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get agreement: {str(e)}")

@app.get("/api/agreements/next_id", response_model=Dict[str, int])
async def get_next_id():
    """Return current next_id from Store; newest agreement id is next_id - 1"""
    try:
        store_resource = await client.account_resource(
            AccountAddress.from_hex(MODULE_ADDRESS),
            f"{MODULE_ADDRESS}::tuition_escrow_v2::Store",
        )
        if not store_resource or not isinstance(store_resource, dict):
            raise HTTPException(status_code=404, detail="Store resource not found")
        data = store_resource.get("data") or {}
        next_id_val = data.get("next_id")
        if next_id_val is None:
            raise HTTPException(status_code=500, detail="Malformed Store resource")
        return {"next_id": int(next_id_val)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get next_id: {str(e)}")

# ...existing code...
@app.get("/api/agreements", response_model=List[AgreementSummary])
async def list_agreements():
    """List all agreements (placeholder - would need to parse Store resource)"""
    # This would require parsing the Store resource to get all agreements
    # For now, return empty list
    return []

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)

