"""Run the whole pipeline in-process, offline (no API key, no server needed).

    python -m scripts.demo

Uses the regex baseline instead of an LLM and an in-memory database, then walks one
customer through a two-email conversation to a carrier quote.
"""
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.portal_client import HttpPortalClient

LINE = "=" * 72


def show(title: str, text: str) -> None:
    print(f"\n{LINE}\n{title}\n{LINE}\n{text}")


def main() -> None:
    app = create_app(Settings(database_url="sqlite://", portal_driver="http"))
    with TestClient(app) as client:
        # the mock carrier portal is part of this app; route the automation to it
        app.state.service.portal = HttpPortalClient(client=client)
        sender = "owner@sweetcrumbs.com"

        email1 = ("Hi, I own Sweet Crumbs Bakery in Columbus, Ohio. We have 6 employees. "
                  "Looking for general liability and workers' comp. Thanks, Maria")
        show("1) CUSTOMER EMAIL (incomplete)", email1)
        r1 = client.post("/inbound", json={"sender_email": sender, "body": email1}).json()
        show(f"   -> status={r1['status']}  still missing={r1['missing']}\n   AGENT REPLY", r1["reply"])

        email2 = "Sorry about that! We did about $450,000 in revenue last year."
        show("2) CUSTOMER REPLY", email2)
        r2 = client.post("/inbound", json={"sender_email": sender, "body": email2}).json()
        show(f"   -> status={r2['status']}  quote={r2['quote']}\n   AGENT REPLY", r2["reply"])

        case = client.get(f"/cases/{r1['case_id']}").json()
        show("3) STORED CASE", "\n".join([
            f"status:     {case['status']}",
            f"submission: {case['submission']}",
            f"messages:   {[m['direction'] for m in case['messages']]}",
            f"portal run: driver={case['portal_runs'][0]['driver']} attempts={case['portal_runs'][0]['attempts']}",
        ]))


if __name__ == "__main__":
    main()
