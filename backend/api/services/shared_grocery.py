"""Owner and accepted membership scope for household shopping lists."""
from django.db.models import Exists, F, OuterRef, Q
from django.http import Http404
from django.shortcuts import get_object_or_404

from api.models import GroceryListMember, GroceryShoppingList


def visible_lists(user):
    member = GroceryListMember.objects.filter(shopping_list_id=OuterRef("pk"), user=user, accepted=True)
    return GroceryShoppingList.objects.filter(Q(owner=user) | (Q(shared=True) & Exists(member)))


def writable_list(user, pk, *, owner_only=False, invited=False, require_shared=True):
    if invited:
        membership = GroceryListMember.objects.filter(shopping_list_id=OuterRef("pk"), user=user, accepted=False)
        rows = GroceryShoppingList.objects.filter(shared=True).filter(Exists(membership))
    else:
        rows = GroceryShoppingList.objects.filter(owner=user) if owner_only else visible_lists(user)
        if require_shared:
            rows = rows.filter(shared=True)
    rows = rows.filter(pk=pk)
    # Acquire the same parent write lock everywhere, including SQLite. Recheck
    # membership after any wait so a concurrent revocation wins before the edit.
    if not rows.update(edit_version=F("edit_version") + 1):
        raise Http404
    return get_object_or_404(rows)
