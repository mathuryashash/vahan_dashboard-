"""One-time bootstrap for the first admin account -- there's no
self-registration (see app/api/v1/endpoints/users.py), so someone has to
exist before any user management via the API is possible. Every account
after this one can be created through the API by an existing admin.

Usage: python -m app.scripts.create_admin --email you@company.com --name "Your Name"
(prompts for a password; pass --password to skip the prompt, e.g. in CI)
"""
import argparse
import asyncio
import getpass

from sqlalchemy import select

from app.core.auth import hash_password
from app.core.database import AsyncSessionLocal, init_db
from app.models.models import User, UserRole


async def main(email: str, password: str, full_name: str | None) -> None:
    await init_db()
    async with AsyncSessionLocal() as db:
        existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if existing is not None:
            print(f"A user with email {email!r} already exists (role={existing.role}). Nothing to do.")
            return
        user = User(
            email=email,
            hashed_password=hash_password(password),
            full_name=full_name,
            role=UserRole.ADMIN,
        )
        db.add(user)
        await db.commit()
        print(f"Created admin user {email!r}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default=None, help="Full name (optional)")
    parser.add_argument("--password", default=None, help="Omit to be prompted (recommended -- avoids shell history)")
    args = parser.parse_args()
    pw = args.password or getpass.getpass("Password for the new admin: ")
    asyncio.run(main(args.email, pw, args.name))
