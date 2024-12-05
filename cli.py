from auth import hash_password
import sys


def run():
    if len(sys.argv) < 2:
        print("cli.py <text to hash>")
        return
    print(hash_password(sys.argv[1]))

if __name__ == "__main__":
    run()