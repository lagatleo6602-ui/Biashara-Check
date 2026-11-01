"""Check the M-Pesa (Daraja) settings from the command line.

    python -m app.mpesa_check                  # just log in to Daraja
    python -m app.mpesa_check 0712345678       # also send a KES 1 PIN prompt (sandbox) to that phone
"""
import sys
import time

from dotenv import load_dotenv

load_dotenv()

from . import mpesa  # noqa: E402
from .contacts import clean_phone  # noqa: E402


def main() -> None:
    r = mpesa.check_connection()
    print(("OK   " if r["ok"] else "FAIL ") + r["message"])
    if not r["ok"] or len(sys.argv) < 2:
        return
    phone = clean_phone(sys.argv[1])
    amount = 1 if mpesa.mode() == "sandbox" else int(input("Amount in KES to request: "))
    out = mpesa.stk_push(phone, amount, "TEST", "Check")
    print(f"Prompt sent to {phone}. Enter your M-Pesa PIN on the phone (or cancel it). Waiting...")
    for _ in range(30):
        time.sleep(4)
        res = mpesa.stk_query(out["checkout_id"])
        if res["state"] != "pending":
            print(res["state"].upper() + ": " + res["desc"])
            return
    print("No answer after 2 minutes.")


if __name__ == "__main__":
    main()
