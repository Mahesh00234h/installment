### Tuition Payment Plans on Aptos

Smart-contract escrow that schedules and automates tuition installments with penalties and grace rules.

#### Stack
- Frontend: HTML + Fetch
- Backend: Python (FastAPI)
- Chain: Aptos Move smart contract (Devnet)

---

### Quick start

1) Prerequisites
- Python 3.10+
- Node not required
- Aptos CLI installed: `cargo install --git https://github.com/aptos-labs/aptos-core.git aptos` or download from releases

2) Create an Aptos account (payer) and fund it on Devnet
- Initialize CLI profile (accept defaults, choose Devnet when prompted):
```bash
aptos init --profile payer --network devnet
```
- This prints an address like `0xabc...`. Fund it from the Devnet faucet: `aptos account fund-with-faucet --account <ADDRESS> --network devnet`

3) Publish the Move contract
- The named address in `move/Move.toml` is already set to your address: `0x12eaa49bdbe263a3430b187f79b11a6e257c1226826bd6115afa1d3ef4c7e93c`
- From the `move/` folder, publish to devnet using the `payer` profile:
```bash
aptos move publish --profile payer --named-addresses TuitionEscrow=0x12eaa49bdbe263a3430b187f79b11a6e257c1226826bd6115afa1d3ef4c7e93c --included-artifacts none
```
- The on-chain store is initialized automatically by the module's `init_module` during publish. No manual call is required.

4) Configure backend
- The `backend/.env` file is already created with your credentials
- Your configuration:
  - `NODE_URL=https://fullnode.devnet.aptoslabs.com/v1`
  - `PAYER_PRIVATE_KEY_HEX=ed25519-priv-0x12eaa49bdbe263a3430b187f79b11a6e257c1226826bd6115afa1d3ef4c7e93c`
  - `PAYER_ADDRESS=0x12eaa49bdbe263a3430b187f79b11a6e257c1226826bd6115afa1d3ef4c7e93c`
  - `MODULE_ADDRESS=0x12eaa49bdbe263a3430b187f79b11a6e257c1226826bd6115afa1d3ef4c7e93c`

5) Install and run backend
```bash
cd backend
python -m venv .venv
. .venv/bin/activate  # Windows PowerShell: .venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

Windows one-step helper
- You can run a helper script that creates a venv, installs deps, generates and funds a new devnet account, and writes `backend/.env`:
```powershell
pwsh -File .\scripts\setup_windows.ps1
```
Note: The script will generate a new account, but you can manually update `backend/.env` to use your existing address `0x89019004bafcc06620c787f2d1be274da2c78005102a3a98b1eef112e242911f` instead.

6) Open frontend
- Open `frontend/index.html` in your browser (or serve it via any static server). It calls `http://localhost:8000` by default.

---

### What it does
- Create an agreement: schedules N installments of amount X APT every `interval_secs`, with a `grace_period_secs` and a late penalty in basis points (`penalty_bps`).
- Pay next installment: backend signs and submits the on-chain call using your payer key.

Important: True “automation” on-chain needs an off-chain scheduler to trigger payments. This demo ships a simple, optional background job (disabled by default) that could auto-pay when due if the payer account holds sufficient balance.

---

### API (backend)
- POST `/api/agreements`
  - body: `{ beneficiary, installment_amount, total_installments, start_time_secs, interval_secs, penalty_bps, grace_period_secs }`
  - returns: `{ tx_hash, agreement_id }` (agreement id parsed from events)

- POST `/api/agreements/{agreement_id}/pay`
  - returns: `{ tx_hash }`

- GET `/api/health`

Amounts are in Octas (1 APT = 10^8 Octas).

---

### Update keys later
If you haven’t created a wallet yet, do steps 2 and 4 later. Then restart the backend.

To switch accounts or networks, just update `.env` and restart the server.

**Note**: Your address `0x12eaa49bdbe263a3430b187f79b11a6e257c1226826bd6115afa1d3ef4c7e93c` is already configured in the Move contract and env template.

---

### Notes
- Move module uses `aptos_coin::AptosCoin` for simplicity. Extending to other coins requires adding generic tables and entry functions.
- Agreement IDs are monotonically increasing and emitted via `AgreementCreatedEvent`.
- Penalty is applied once per installment if paid after `due + grace`.

