from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connections
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import GroceryListItem, GroceryListMember, GroceryShoppingList, Transaction

URL = "/api/grocery/lists/"


def signed_in(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


class HouseholdTests(TestCase):
    def setUp(self):
        users = get_user_model().objects
        self.owner = users.create_user(username="groceries-owner")
        self.member = users.create_user(username="groceries-member")
        self.stranger = users.create_user(username="groceries-stranger")
        self.host = signed_in(self.owner)
        self.guest = signed_in(self.member)
        self.outside = signed_in(self.stranger)
        created = self.host.post(URL, {"name": "Household", "shared": True, "items": []}, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.path = f"{URL}{created.data['id']}/"

    def invite(self):
        invite = self.host.post(self.path + "members/", {"username": self.member.username}, format="json")
        self.assertEqual(invite.status_code, 201)
        return invite.data["id"]

    def join(self):
        invite_id = self.invite()
        self.assertEqual(self.guest.post(self.path + "invitation/", {"accept": True}, format="json").status_code, 204)
        return invite_id

    def add(self, client, name="milk", unit="l"):
        response = client.post(self.path + "items/", {"name": name, "quantity": "1", "unit": unit}, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data

    def test_invitation_acceptance_and_immediate_revocation(self):
        invitation = self.invite()
        for client in (self.guest, self.outside):
            self.assertEqual(client.get(self.path).status_code, 404)
            self.assertEqual(client.get(self.path + "household/").status_code, 404)
            self.assertEqual(client.post(self.path + "items/", {"name": "milk", "quantity": "1", "unit": "l"},
                                         format="json").status_code, 404)
        self.assertEqual(self.outside.get(URL + "invitations/").data, [])
        self.assertEqual(self.outside.post(self.path + "invitation/", {"accept": True}, format="json").status_code, 404)
        self.assertEqual(self.guest.get(URL + "invitations/").data[0]["name"], "Household")
        self.assertEqual(self.guest.post(self.path + "invitation/", {"accept": True}, format="json").status_code, 204)
        self.assertEqual(self.guest.get(URL).data[0]["name"], "Household")
        self.assertEqual(self.guest.get(self.path + "household/").data["members"], [])
        self.assertEqual(self.guest.delete(self.path).status_code, 404)
        self.assertEqual(self.guest.post(self.path + "members/", {"username": self.stranger.username}, format="json").status_code, 404)
        self.assertEqual(self.guest.delete(self.path + f"members/{invitation}/").status_code, 404)
        item = self.add(self.guest)
        self.assertEqual(self.host.delete(self.path + f"members/{invitation}/").status_code, 204)
        self.assertEqual(self.guest.get(URL).data, [])
        self.assertEqual(self.guest.get(self.path + "household/").status_code, 404)
        self.assertEqual(self.guest.patch(self.path + f"items/{item['id']}/", {"revision": 0, "quantity": "2"},
                                          format="json").status_code, 404)
        self.assertEqual(self.guest.post(self.path + "optimize/").status_code, 404)

    def test_item_attribution_versions_and_optimizer_use_only_open_items(self):
        self.join()
        milk = self.add(self.guest)
        self.add(self.host, "rice", "kg")
        target = self.path + f"items/{milk['id']}/"
        self.assertEqual(milk["added_by"], self.member.username)
        changed = self.host.patch(target, {"revision": 0, "quantity": "2.5", "purchased": True}, format="json")
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.data["completed_by"], self.owner.username)
        self.assertEqual(changed.data["revision"], 1)
        self.assertEqual(self.guest.patch(target, {"revision": 0, "quantity": "3"}, format="json").status_code, 409)
        self.assertEqual(self.guest.delete(target + "?revision=0").status_code, 409)
        with patch("api.views.shared_grocery.optimize_basket", return_value={"fixture": True}) as optimizer:
            self.assertEqual(self.guest.post(self.path + "optimize/").status_code, 200)
        self.assertEqual([row["name"] for row in optimizer.call_args.kwargs["items"]], ["rice"])
        self.assertEqual(self.guest.delete(target + "?revision=1").status_code, 204)

    def test_revocation_during_optimization_blocks_the_result(self):
        invitation = self.join()
        self.add(self.host)

        def optimize(**kwargs):
            response = self.host.delete(self.path + f"members/{invitation}/")
            self.assertEqual(response.status_code, 204)
            return {"fixture": True}

        with patch("api.views.shared_grocery.optimize_basket", side_effect=optimize):
            self.assertEqual(self.guest.post(self.path + "optimize/").status_code, 404)

    def test_existing_private_lists_can_be_shared_without_sharing_the_ledger(self):
        purchase = Transaction.objects.create(
            user=self.owner, amount="-20", category="groceries", particulars="Private", timestamp=timezone.now(),
        )
        legacy = self.host.post(URL, {"name": "Private list", "items": [
            {"name": "Rice", "quantity": "1000", "unit": "g"},
        ]}, format="json")
        self.assertEqual(legacy.data["settings"]["items"][0]["unit"], "kg")
        path = f"{URL}{legacy.data['id']}/"
        self.assertEqual(self.guest.get(path).status_code, 404)
        self.assertEqual(self.host.post(path + "household/").status_code, 204)
        self.assertEqual(self.host.post(path + "household/").status_code, 204)
        self.assertEqual(len(self.host.get(path + "household/").data["items"]), 1)
        self.host.post(path + "members/", {"username": self.member.username}, format="json")
        self.guest.post(path + "invitation/", {"accept": True}, format="json")
        self.assertEqual(self.guest.get(path + "household/").data["items"][0]["product"]["name"], "Rice")
        self.assertEqual(self.guest.get("/api/transactions/").data, [])
        self.assertTrue(Transaction.objects.filter(pk=purchase.pk, user=self.owner).exists())
        self.assertEqual(self.guest.get("/api/receipts/").data["count"], 0)
        self.assertEqual(self.guest.get("/api/budgets/").status_code, 200)


class ConcurrentHouseholdTests(TransactionTestCase):
    def test_only_one_simultaneous_write_can_use_the_same_revision(self):
        users = get_user_model().objects
        owner = users.create_user(username="concurrent-owner")
        member = users.create_user(username="concurrent-member")
        record = GroceryShoppingList.objects.create(owner=owner, name="Together", shared=True, settings={"items": []})
        GroceryListMember.objects.create(shopping_list=record, user=member, accepted=True)
        row = GroceryListItem.objects.create(
            shopping_list=record, added_by=owner,
            product={"name": "milk", "quantity": "1", "unit": "l", "preferred_brand": "", "allow_substitutions": True},
        )
        ready = Barrier(2, timeout=5)

        def edit(user, quantity):
            try:
                client = signed_in(user)
                ready.wait()
                response = client.patch(f"{URL}{record.pk}/items/{row.pk}/", {
                    "revision": 0, "quantity": quantity,
                }, format="json")
                return response.status_code, quantity
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda pair: edit(*pair), [(owner, "2"), (member, "3")]))
        self.assertEqual(sorted(code for code, _ in results), [200, 409])
        row.refresh_from_db()
        self.assertEqual(row.revision, 1)
        winning_quantity = next(value for code, value in results if code == 200)
        self.assertEqual(Decimal(row.product["quantity"]), Decimal(winning_quantity))
