import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.routes import add_instagram_creator
from app.db import Base
from app.ingestion.instagram import InstagramConnector
from app.models import Account, Creator
from app.schemas import InstagramAccountResolve


class InstagramCreatorLookupTests(unittest.TestCase):
    def test_resolve_account_accepts_username_and_returns_profile_data(self):
        connector = InstagramConnector("secret-test-token")
        with patch.object(
            connector,
            "_get",
            return_value={
                "user_id": "123456789",
                "username": "realcreator",
                "name": "Real Creator",
                "followers_count": 321,
            },
        ) as get:
            profile = connector.resolve_account("@RealCreator")

        self.assertEqual(profile, {
            "id": "123456789",
            "username": "realcreator",
            "name": "Real Creator",
            "followers": 321,
        })
        get.assert_called_once_with(
            "me", fields="user_id,username,name,followers_count"
        )

    def test_resolve_account_accepts_instagram_user_id_from_list_response(self):
        connector = InstagramConnector("secret-test-token")
        with patch.object(
            connector,
            "_get",
            return_value={
                "data": [
                    {
                        "user_id": "123456789",
                        "username": "realcreator",
                        "followers_count": 321,
                    }
                ]
            },
        ):
            profile = connector.resolve_account("123456789")

        self.assertEqual(profile["id"], "123456789")
        self.assertEqual(profile["name"], "realcreator")

    def test_resolve_account_rejects_accounts_not_authorized_by_token(self):
        connector = InstagramConnector("secret-test-token")
        with patch.object(
            connector,
            "_get",
            return_value={
                "user_id": "123456789",
                "username": "realcreator",
                "followers_count": 321,
            },
        ):
            with self.assertRaisesRegex(PermissionError, "not authorized"):
                connector.resolve_account("someone_else")

    def test_resolve_account_rejects_invalid_profile_data(self):
        connector = InstagramConnector("secret-test-token")
        with patch.object(
            connector,
            "_get",
            return_value={
                "user_id": "123456789",
                "username": "realcreator",
                "followers_count": None,
            },
        ):
            with self.assertRaisesRegex(ValueError, "invalid follower count"):
                connector.resolve_account("realcreator")

    def test_api_registers_verified_account_and_follower_count(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        try:
            with Session(engine) as session:
                connector = SimpleNamespace(
                    resolve_account=lambda _: {
                        "id": "123456789",
                        "username": "realcreator",
                        "name": "Real Creator",
                        "followers": 321,
                    }
                )
                request = SimpleNamespace(
                    app=SimpleNamespace(
                        state=SimpleNamespace(
                            ingestion=SimpleNamespace(
                                connectors={"instagram": connector}
                            )
                        )
                    )
                )
                result = add_instagram_creator(
                    InstagramAccountResolve(identifier="@realcreator"),
                    request,
                    session,
                )

                account = session.scalar(
                    select(Account).where(Account.external_id == "123456789")
                )
                creator = session.get(Creator, account.creator_id)
                self.assertEqual(result["instagram_account"]["username"], "realcreator")
                self.assertEqual(result["instagram_account"]["followers"], 321)
                self.assertEqual(account.handle, "realcreator")
                self.assertEqual(account.followers, 321)
                self.assertEqual(creator.name, "Real Creator")
        finally:
            Base.metadata.drop_all(engine)
            engine.dispose()

    def test_api_requires_instagram_connector(self):
        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(ingestion=SimpleNamespace(connectors={}))
            )
        )
        with self.assertRaises(HTTPException) as caught:
            add_instagram_creator(
                InstagramAccountResolve(identifier="realcreator"),
                request,
                None,
            )

        self.assertEqual(caught.exception.status_code, 400)

    def test_api_surfaces_token_account_mismatch(self):
        connector = SimpleNamespace(
            resolve_account=lambda _: (_ for _ in ()).throw(
                PermissionError("token cannot access this username")
            )
        )
        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    ingestion=SimpleNamespace(connectors={"instagram": connector})
                )
            )
        )
        with self.assertRaises(HTTPException) as caught:
            add_instagram_creator(
                InstagramAccountResolve(identifier="someone_else"),
                request,
                None,
            )

        self.assertEqual(caught.exception.status_code, 403)
        self.assertIn("token cannot access", caught.exception.detail)

    def test_api_surfaces_meta_error_without_exposing_token(self):
        token = "private-test-token"
        response = httpx.Response(
            400,
            json={
                "error": {
                    "message": f"Invalid token {token}",
                    "type": "OAuthException",
                    "code": 190,
                }
            },
            request=httpx.Request("GET", "https://graph.instagram.com/v26.0/me"),
        )
        connector = SimpleNamespace(
            token=token,
            resolve_account=lambda _: (_ for _ in ()).throw(
                httpx.HTTPStatusError("provider failure", request=response.request, response=response)
            ),
        )
        request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    ingestion=SimpleNamespace(connectors={"instagram": connector})
                )
            )
        )

        with self.assertRaises(HTTPException) as caught:
            add_instagram_creator(
                InstagramAccountResolve(identifier="realcreator"),
                request,
                None,
            )

        self.assertEqual(caught.exception.status_code, 502)
        self.assertIn("HTTP 400, code 190", caught.exception.detail)
        self.assertIn("[redacted]", caught.exception.detail)
        self.assertNotIn(token, caught.exception.detail)


if __name__ == "__main__":
    unittest.main()
