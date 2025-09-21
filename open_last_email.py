import os
import glob
import shutil
import webbrowser

# folder where Django is saving emails
EMAIL_DIR = os.path.join(os.path.dirname(__file__), "tmp_emails")

def open_latest_email():
    files = glob.glob(os.path.join(EMAIL_DIR, "*.log"))
    if not files:
        print("No email files found in tmp_emails/")
        return

    latest_file = max(files, key=os.path.getmtime)
    print(f"Latest email: {latest_file}")

    # Print subject and recipient if available
    try:
        with open(latest_file, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.startswith("Subject:"):
                    print(line.strip())
                if line.startswith("To:"):
                    print(line.strip())
    except Exception as e:
        print(f"Could not read email headers: {e}")

    # copy to test_email.html
    dest = os.path.join(EMAIL_DIR, "test_email.html")
    shutil.copy(latest_file, dest)

    # open in default browser
    webbrowser.open(f"file://{dest}")

if __name__ == "__main__":
    open_latest_email()