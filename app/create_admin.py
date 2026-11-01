"""Create (or reset) an admin account.

Run from the project folder with the venv active:
    python -m app.create_admin
"""
import getpass

from sqlalchemy import func, select

from .auth import MIN_PASSWORD, hash_password
from .database import Base, SessionLocal, engine
from .invites import ensure_super_admin
from .models import User


def main() -> None:
    Base.metadata.create_all(bind=engine)
    username = input("Admin username [admin]: ").strip().lower() or "admin"
    while True:
        password = getpass.getpass(f"Password (at least {MIN_PASSWORD} characters, typing is hidden): ")
        if len(password) < MIN_PASSWORD:
            print("Too short, try again.")
            continue
        if password != getpass.getpass("Type it again: "):
            print("The two passwords don't match, try again.")
            continue
        break
    with SessionLocal() as db:
        user = db.scalar(select(User).where(func.lower(User.username) == username))
        if user and user.role != "admin":
            print(f"'{username}' is already used by a business owner. Pick another username.")
            return
        if user:
            user.password_hash, user.is_active = hash_password(password), True
            print(f"Password for admin '{username}' updated.")
        else:
            db.add(User(username=username, password_hash=hash_password(password), role="admin"))
            print(f"Admin '{username}' created. Log in at http://127.0.0.1:8000/login")
        db.flush()
        boss = ensure_super_admin(db)
        db.commit()
        if boss:
            print(f"Super admin: '{boss.username}' (the only one who can generate admin codes).")


if __name__ == "__main__":
    main()
