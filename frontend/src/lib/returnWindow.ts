import type { Customer, Order, OrderItem } from "./api";

/** Matches backend demo clock in `app/agent/tools.py`. */
export const DEMO_TODAY = new Date("2026-06-22T12:00:00");

export type ReturnWindowTone = "positive" | "warning" | "expired" | "muted";

export type ReturnWindowInfo = {
  allowedDays: number;
  daysSinceDelivery: number | null;
  daysRemaining: number | null;
  eligible: boolean;
  label: string;
  tone: ReturnWindowTone;
};

export type PurchasedProduct = OrderItem & {
  orderId: string;
  orderTotal: number;
  orderStatus: string;
  deliveredDate: string | null;
  shippingCountry: string;
};

function startOfDay(value: Date): Date {
  return new Date(value.getFullYear(), value.getMonth(), value.getDate());
}

function daysBetween(later: Date, earlier: Date): number {
  const msPerDay = 24 * 60 * 60 * 1000;
  return Math.floor((startOfDay(later).getTime() - startOfDay(earlier).getTime()) / msPerDay);
}

export function getAllowedReturnDays(
  customer: Pick<Customer, "lifetime_value" | "notes">,
  order: Pick<Order, "shipping_country">,
): number {
  const notes = customer.notes.toLowerCase();
  if (notes.includes("business account")) {
    return 15;
  }
  if (order.shipping_country && order.shipping_country !== "US") {
    return 20;
  }
  if (customer.lifetime_value > 5000 || notes.includes("vip: yes")) {
    return 45;
  }
  return 30;
}

function productRestrictionLabel(item: OrderItem): string | null {
  if (item.final_sale) {
    return "Final sale — not eligible for return";
  }
  if (item.digital_download || item.condition === "digital_delivered") {
    return "Digital product — not eligible for return";
  }
  if (item.subscription_product) {
    return "Subscription — contact support to cancel";
  }
  return null;
}

export function getReturnWindowInfo(
  customer: Pick<Customer, "lifetime_value" | "notes">,
  order: Pick<Order, "status" | "delivered_date" | "shipping_country">,
): ReturnWindowInfo {
  const allowedDays = getAllowedReturnDays(customer, order);

  if (order.status === "returned") {
    return {
      allowedDays,
      daysSinceDelivery: null,
      daysRemaining: null,
      eligible: false,
      label: "Returned — no longer eligible",
      tone: "muted",
    };
  }

  if (order.status === "lost") {
    return {
      allowedDays,
      daysSinceDelivery: null,
      daysRemaining: null,
      eligible: false,
      label: "Lost shipment — contact support",
      tone: "warning",
    };
  }

  if (order.status !== "delivered" || !order.delivered_date) {
    return {
      allowedDays,
      daysSinceDelivery: null,
      daysRemaining: null,
      eligible: false,
      label: "Return window starts after delivery",
      tone: "muted",
    };
  }

  const delivered = new Date(`${order.delivered_date}T12:00:00`);
  const daysSinceDelivery = daysBetween(DEMO_TODAY, delivered);
  const daysRemaining = allowedDays - daysSinceDelivery;
  const eligible = daysRemaining >= 0;

  if (!eligible) {
    const expiredBy = Math.abs(daysRemaining);
    return {
      allowedDays,
      daysSinceDelivery,
      daysRemaining,
      eligible: false,
      label:
        expiredBy === 1
          ? "Return window expired yesterday"
          : `Return window expired · ${expiredBy} days ago`,
      tone: "expired",
    };
  }

  if (daysRemaining === 0) {
    return {
      allowedDays,
      daysSinceDelivery,
      daysRemaining,
      eligible: true,
      label: "Last day to return",
      tone: "warning",
    };
  }

  if (daysRemaining === 1) {
    return {
      allowedDays,
      daysSinceDelivery,
      daysRemaining,
      eligible: true,
      label: "1 day left to return",
      tone: "warning",
    };
  }

  return {
    allowedDays,
    daysSinceDelivery,
    daysRemaining,
    eligible: true,
    label: `${daysRemaining} days left to return`,
    tone: daysRemaining <= 7 ? "warning" : "positive",
  };
}

export function getProductReturnLabel(
  customer: Pick<Customer, "lifetime_value" | "notes">,
  item: PurchasedProduct,
): ReturnWindowInfo {
  const restriction = productRestrictionLabel(item);
  const window = getReturnWindowInfo(customer, {
    status: item.orderStatus as Order["status"],
    delivered_date: item.deliveredDate,
    shipping_country: item.shippingCountry,
  });

  if (restriction) {
    return {
      ...window,
      eligible: false,
      label: restriction,
      tone: "expired",
    };
  }

  return window;
}
