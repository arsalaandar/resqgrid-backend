class ConsoleOTPProvider:
    def send_otp(self, phone: str, code: str) -> None:
        print(
            f"\n[DEV ONLY] OTP for {phone}: {code}\n",
            flush=True,
        )
