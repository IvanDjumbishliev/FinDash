import kaufland from "./assets/kaufland-logo.svg";
import lidl from "./assets/lidl-logo.svg";
import fantastico from "./assets/fantastico-logo.png";

export const retailers = {
  lidl: { name: "Lidl", image: lidl },
  kaufland: { name: "Kaufland", image: kaufland },
  fantastico: { name: "Fantastico", image: fantastico },
};
export const retailerIds = Object.keys(retailers);
export const units = { kg: "kg", g: "g", l: "L", ml: "mL", item: "items" };

export function basketSettings(items, options) {
  return {
    ...options,
    max_stores: Math.min(options.max_stores, options.retailers.length),
    items: items.map(({ name, quantity, unit, preferred_brand, allow_substitutions }) => ({
      name: name.trim(), quantity, ...(unit && { unit }), preferred_brand: preferred_brand.trim(), allow_substitutions,
    })),
  };
}

export function errorText(error, fallback) {
  function collect(value) {
    if (typeof value === "string") return [value];
    if (Array.isArray(value)) return value.flatMap(collect);
    return value && typeof value === "object" ? Object.values(value).flatMap(collect) : [];
  }
  return collect(error.response?.data).join(" ") || fallback;
}
