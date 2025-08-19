import os
import sys
import argparse
import requests
from dotenv import load_dotenv
from aptos_sdk.account import Account


def load_account_from_env() -> Account:

	load_dotenv()
	pk = os.getenv("PAYER_PRIVATE_KEY_HEX", "").strip()
	if not pk:
		raise SystemExit("PAYER_PRIVATE_KEY_HEX not set in .env")

	if pk.startswith("ed25519-priv-"):
		pk = pk[14:]
	if pk.startswith("0x"):
		pk = pk[2:]
	elif pk.startswith("x"):
		pk = pk[1:]
	pk = "0x" + pk
	return Account.load_key(pk)


def fund(address_hex: str, amount: int) -> None:

	faucet_url = os.getenv("FAUCET_URL", "https://faucet.devnet.aptoslabs.com")
	url = f"{faucet_url}/mint?amount={amount}&address={address_hex}"
	r = requests.post(url, timeout=30)
	if r.status_code >= 400:
		raise SystemExit(f"Faucet error {r.status_code}: {r.text}")
	print(f"Faucet response: {r.text}")


def main() -> None:

	parser = argparse.ArgumentParser()
	parser.add_argument("--amount", type=int, default=200_000_000, help="Amount in octas to request from faucet")
	args = parser.parse_args()

	acct = load_account_from_env()
	addr = acct.address()
	print(f"Derived address: {addr}")
	fund(str(addr), args.amount)
	print("Funding requested. If needed, run again to top up more.")


if __name__ == "__main__":
	main()

