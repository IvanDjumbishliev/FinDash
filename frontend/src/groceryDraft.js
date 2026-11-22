export const maxDraftItems = 40;
export const defaultGroceryItem = { quantity: "1", unit: "", preferred_brand: "", allow_substitutions: true };

export function groceryDraft(account, storage = sessionStorage) {
  try {
    const draft = account == null ? null : JSON.parse(storage.getItem(`findash:grocery-draft:${account}`));
    return draft && Array.isArray(draft.items) && draft.items.length <= maxDraftItems ? draft : null;
  } catch {
    return null;
  }
}

export function storeGroceryDraft(account, draft, storage = sessionStorage) {
  if (account == null) return false;
  try {
    storage.setItem(`findash:grocery-draft:${account}`, JSON.stringify(draft));
    return true;
  } catch {
    return false;
  }
}

export function addCatalogPackage(draft, offer) {
  const items = draft?.items ?? [];
  if (items.some((item) => item.offer_id === offer.id || (
    item.name.trim().toLowerCase() === offer.name.trim().toLowerCase()
    && item.unit === offer.unit && item.preferred_brand.toLowerCase() === (offer.brand || "").toLowerCase()
  ))) return { error: "This product is already in your shopping list. Adjust the quantity in the optimizer." };
  if (items.length >= maxDraftItems) return { error: "Your shopping list is full. Remove an item before adding another." };
  const id = items.reduce((largest, item) => Math.max(largest, item.id), 0) + 1;
  return {
    items: [...items, {
      ...defaultGroceryItem, id, offer_id: offer.id, name: offer.name, quantity: offer.quantity,
      unit: offer.unit, preferred_brand: offer.brand || "", image_url: offer.image_url,
    }],
    options: { ...draft?.options, currency: items.length && draft?.options?.currency ? draft.options.currency : offer.currency },
  };
}
