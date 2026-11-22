export const MAX_RECEIPT_BYTES = 8 * 1024 * 1024;
export const MAX_RECEIPT_IMAGES = 3;
export const MAX_RECEIPT_ITEMS = 200;
export const ACCEPTED_RECEIPT_IMAGES = ".jpg,.jpeg,.png,.webp,.heic,.heif,image/jpeg,image/png,image/webp,image/heic,image/heif";

export function validateReceiptImages(files) {
  if (files.length > MAX_RECEIPT_IMAGES) return "Choose up to three photos of the same receipt.";
  if (files.some((file) => !/\.(jpe?g|png|webp|heic|heif)$/i.test(file.name))) {
    return "Choose a JPEG, PNG, WebP, or HEIC/HEIF photo.";
  }
  if (files.some((file) => !file.size)) return "One of the selected photos is empty.";
  if (files.reduce((total, file) => total + file.size, 0) > MAX_RECEIPT_BYTES) {
    return "The selected photos must total 8 MB or less.";
  }
  return "";
}

export async function rotateReceiptFile({ file, turns }) {
  if (!turns) return file;
  let image;
  try {
    image = await createImageBitmap(file, { imageOrientation: "from-image" });
    const canvas = document.createElement("canvas");
    const scale = Math.min(1, 3000 / Math.max(image.width, image.height));
    const width = Math.max(1, Math.round(image.width * scale));
    const height = Math.max(1, Math.round(image.height * scale));
    [canvas.width, canvas.height] = turns % 2 ? [height, width] : [width, height];
    const context = canvas.getContext("2d");
    context.fillStyle = "white";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.translate(canvas.width / 2, canvas.height / 2);
    context.rotate(turns * Math.PI / 2);
    context.drawImage(image, -width / 2, -height / 2, width, height);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.92));
    if (!blob) throw new Error("Image encoding failed");
    return new File([blob], file.name.replace(/\.[^.]+$/, ".jpg"), { type: "image/jpeg" });
  } catch {
    throw new Error("This photo could not be rotated in your browser. Undo the rotation or choose another image.");
  } finally {
    image?.close();
  }
}

const decimal = (value) => String(value ?? "").trim().replace(",", ".");

export function cents(value) {
  const match = /^(-?)(\d{1,10})(?:\.(\d{1,2}))?$/.exec(decimal(value));
  if (!match) return null;
  return (match[1] ? -1 : 1) * (Number(match[2]) * 100 + Number((match[3] || "").padEnd(2, "0")));
}

export function receiptTotals(items, total) {
  const prices = items.map((item) => cents(item.line_total));
  const itemTotal = prices.length && prices.every((price) => price != null)
    ? prices.reduce((sum, price) => sum + price, 0) : null;
  const receiptTotal = cents(total);
  return {
    itemTotal,
    receiptTotal,
    difference: itemTotal != null && receiptTotal != null ? receiptTotal - itemTotal : null,
  };
}

const sofiaClock = new Intl.DateTimeFormat("en-GB", {
  timeZone: "Europe/Sofia", year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
});

function sofiaWallTime(timestamp) {
  const date = new Date(timestamp);
  if (!timestamp || Number.isNaN(date.valueOf())) return "";
  const parts = Object.fromEntries(sofiaClock.formatToParts(date).map(({ type, value }) => [type, value]));
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}`;
}

export function reviewFields(receipt) {
  const timestamp = sofiaWallTime(receipt.purchased_at);
  return {
    ...receipt,
    date: timestamp.slice(0, 10) || receipt.purchase_date || "",
    time: timestamp.slice(11, 19),
    items: receipt.items.map((item, index) => ({ ...item, key: index })),
  };
}

function purchaseTimestamp(fields) {
  const { date, time, purchased_at: original } = fields;
  if (!date || !time) return null;
  // Edited Bulgarian receipt times follow Europe/Sofia, independent of the browser's timezone.
  const wallTime = `${date}T${time.length === 5 ? `${time}:00` : time}`;
  if (wallTime === sofiaWallTime(original)) return original;
  const matches = ["+02:00", "+03:00"].map((offset) => `${wallTime}${offset}`)
    .filter((iso) => sofiaWallTime(iso) === wallTime);
  return matches.find((iso) => iso.slice(-6) === original?.slice(-6)) || matches.at(-1) || null;
}

export function confirmationBody(token, fields) {
  const timestamp = purchaseTimestamp(fields);
  if (!timestamp) throw new Error("Enter a valid purchase date and time in Bulgaria.");
  if (!fields.merchant?.trim() || !["EUR", "BGN"].includes(fields.currency)) {
    throw new Error("Enter the merchant and choose the original currency.");
  }
  const amount = (value, label, required = false) => {
    if (!decimal(value) && !required) return null;
    if (cents(value) == null) throw new Error(`Enter a valid ${label} with up to two decimal places.`);
    return decimal(value);
  };
  if (!fields.items.length) throw new Error("Add at least one item from the receipt.");
  const items = fields.items.map((item, index) => {
    if (!item.original_description?.trim()) throw new Error(`Enter a name for item ${index + 1}.`);
    const quantity = decimal(item.quantity);
    const unitPrice = decimal(item.unit_price);
    if (quantity && (!/^-?\d{1,8}(\.\d{1,6})?$/.test(quantity) || Number(quantity) === 0)) {
      throw new Error(`Enter a valid nonzero quantity for item ${index + 1}.`);
    }
    if (unitPrice && !/^-?\d{1,10}(\.\d{1,4})?$/.test(unitPrice)) {
      throw new Error(`Enter a valid unit price for item ${index + 1}.`);
    }
    return {
      original_description: item.original_description.trim(),
      category: item.category?.trim() || "",
      quantity: quantity || null,
      unit: quantity ? item.unit || "" : "",
      unit_price: unitPrice || null,
      line_total: amount(item.line_total, `line total for item ${index + 1}`, true),
      discount: amount(item.discount, `discount for item ${index + 1}`),
      confidence: item.confidence ?? null,
    };
  });
  return {
    token, items, purchased_at: timestamp,
    merchant: fields.merchant.trim(),
    currency: fields.currency,
    total: amount(fields.total, "receipt total", true),
    discounts: amount(fields.discounts, "receipt discount"),
    subtotal: amount(fields.subtotal, "subtotal"),
    tax_total: amount(fields.tax_total, "tax total"),
    reference: fields.reference?.trim() || "",
  };
}

export function receiptApiError(error, fallback) {
  const data = error.response?.data;
  if (!data || typeof data !== "object") return fallback;
  if (typeof data.detail === "string" && data.detail.length <= 300) return data.detail;
  const queue = Object.values(data);
  while (queue.length) {
    const value = queue.shift();
    if (typeof value === "string" && value.length <= 300) return value;
    if (value && typeof value === "object") queue.push(...Object.values(value));
  }
  return fallback;
}

const localDate = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeZone: "Europe/Sofia" });

export function receiptDate(value) {
  return localDate.format(new Date(value));
}
