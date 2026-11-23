import { code128, ean13, ean8, qrcode, upca } from "@bwip-js/browser";

const encoders = { code128, ean13, ean8, qrcode, upca };

export function loyaltyCodeOptions(format, identifier) {
  const square = format === "qrcode";
  return {
    text: identifier, scale: square ? 8 : 3, ...(!square && { height: 20 }),
    paddingwidth: square ? 4 : 12, paddingheight: square ? 4 : 5,
    backgroundcolor: "FFFFFF", barcolor: "000000", includetext: false,
  };
}

export function drawLoyaltyCode(canvas, format, identifier) {
  const encode = Object.hasOwn(encoders, format) ? encoders[format] : null;
  if (!encode) return false;
  encode(canvas, loyaltyCodeOptions(format, identifier));
  return true;
}
