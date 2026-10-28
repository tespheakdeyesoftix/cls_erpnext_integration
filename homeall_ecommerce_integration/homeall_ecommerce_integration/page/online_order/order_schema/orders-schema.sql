-- Consolidated stored-table schema reference from repository migrations through 2026-10-28.
-- This is a reference artifact, not a migration; referenced tables already exist in the application.
-- Original migrations also define RLS, permissions, indexes, triggers and functions.
-- UUID values in the companion JSON examples are illustrative and are not provisioned fixtures.
-- Columns called items/applied_cart_promotions/image_url/promotion_benefit are API-derived, not added here.

create table public.orders (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id),
  erp_customer text,
  status text not null default 'pending' check (status in ('pending', 'accepted', 'rejected', 'processing', 'out_for_delivery', 'delivered', 'completed', 'cancelled')),
  currency text not null,
  total_quantity numeric(16,3) not null,
  subtotal numeric(18,2) not null,
  discount_amount numeric(18,2) not null default 0,
  product_discount_amount numeric(18,2) not null default 0,
  cart_discount_amount numeric(18,2) not null default 0,
  tax_amount numeric(18,2) not null default 0,
  total_amount numeric(18,2) not null,
  erp_order_number text,
  erp_sync_status text not null default 'pending' check (erp_sync_status in ('pending', 'processing', 'synced', 'failed', 'cancelled')),
  idempotency_key uuid not null,
  request_items jsonb not null,
  delivery_address_id uuid,
  delivery_address_snapshot jsonb,
  payment_method text not null default 'cash_on_delivery' check (payment_method in ('cash_on_delivery', 'aba_qr_pay')),
  payment_status text not null default 'pay_on_delivery' check (payment_status in ('pay_on_delivery', 'pending', 'paid', 'failed', 'expired', 'cancelled', 'refunded')),
  note text,
  payment_transaction_id text,
  payment_reference text,
  payment_qr_image_url text,
  payment_expires_at timestamptz,
  pricing_user_type_id uuid,
  pricing_user_type_name text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (user_id, idempotency_key),
  unique (erp_order_number),
  check (currency ~ '^[A-Z]{3}$'),
  check (total_quantity > 0),
  check (subtotal >= 0 and subtotal <= 1000000000000),
  check (discount_amount >= 0),
  check (product_discount_amount >= 0),
  check (cart_discount_amount >= 0),
  check (tax_amount >= 0),
  check (total_amount >= 0),
  check (total_amount = subtotal - discount_amount + tax_amount),
  check (delivery_address_snapshot is null or jsonb_typeof(delivery_address_snapshot) = 'object'),
  check (note is null or length(note) between 1 and 500),
  check (payment_qr_image_url is null or payment_qr_image_url ~ '^https://[^[:space:]]+$')
);

create table public.order_items (
  id uuid primary key default gen_random_uuid(),
  order_id uuid not null references public.orders(id) on delete cascade,
  product_id uuid not null references public.products(id),
  business_id uuid not null references public.business_profiles(id) on delete restrict,
  erp_item_code text not null,
  erp_supplier text,
  product_name text not null,
  line_type text not null default 'purchased' check (line_type in ('purchased', 'free')),
  uom text not null,
  quantity numeric(12,3) not null,
  conversion_factor numeric not null default 1,
  base_uom text not null,
  base_quantity numeric not null,
  source_product_id uuid references public.products(id),
  source_uom text,
  product_price_id uuid references public.product_prices(id) on delete set null,
  base_unit_price numeric(18,6) not null,
  unit_price numeric(14,2) not null,
  discount_type text not null default 'none' check (discount_type in ('none', 'percentage', 'fixed_amount', 'rate', 'free_product')),
  discount_value numeric(18,6) not null default 0,
  product_discount_amount numeric(18,2) not null default 0,
  cart_discount_amount numeric(18,2) not null default 0,
  discount_amount numeric(18,2) not null default 0,
  tax_amount numeric(18,2) not null default 0,
  line_total numeric(18,2) not null,
  pricing_snapshot jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  check (quantity > 0 and quantity <= 10000),
  check (unit_price >= 0),
  check (discount_value >= 0),
  check (discount_amount >= 0),
  check (product_discount_amount >= 0),
  check (cart_discount_amount >= 0),
  check (tax_amount >= 0),
  check (line_total >= 0),
  check (conversion_factor > 0),
  check (jsonb_typeof(pricing_snapshot) = 'object'),
  check (product_discount_amount = round(quantity * base_unit_price, 2) - round(quantity * unit_price, 2)
    and discount_amount = product_discount_amount + cart_discount_amount
    and cart_discount_amount <= round(quantity * unit_price, 2)
    and line_total = round(quantity * unit_price, 2) - cart_discount_amount + tax_amount)
);

create table public.order_promotions (
  id uuid primary key default gen_random_uuid(),
  order_id uuid not null references public.orders(id) on delete cascade,
  promotion_id uuid references public.promotions(id) on delete set null,
  promotion_name text not null,
  application_scope text not null check (application_scope in ('eligible_cart', 'entire_cart')),
  eligibility_basis text not null check (eligibility_basis in ('quantity', 'amount')),
  qualifying_quantity numeric(16,3),
  qualifying_amount numeric(18,2),
  benefit_base_amount numeric(18,2) not null,
  discount_type text not null check (discount_type in ('percentage', 'fixed_amount')),
  discount_value numeric(18,6) not null,
  discount_amount numeric(18,2) not null,
  currency text not null,
  pricing_snapshot jsonb not null,
  created_at timestamptz not null default now(),
  unique (order_id, promotion_id),
  check (benefit_base_amount >= 0),
  check (discount_value > 0),
  check (discount_amount > 0),
  check (currency ~ '^[A-Z]{3}$'),
  check (jsonb_typeof(pricing_snapshot) = 'object')
);

create unique index orders_payment_transaction_key
  on public.orders(payment_transaction_id)
  where payment_transaction_id is not null;

-- Insert behavior in the original migrations:
-- 1. orders.require_order_address_location verifies address ownership and coordinates when address_id is set.
-- 2. order_items.capture_order_uom reads conversion_factor/base_uom/source_uom from pricing_snapshot.
--    It sets base_quantity = quantity * conversion_factor.
-- 3. order_items.prepare_order_item_discount_components reads product/cart components from pricing_snapshot.
-- 4. order_items.capture_order_cart_promotion accumulates order discount components and captures order_promotions.
--    Do not pre-populate order product/cart totals and then let the same triggers add them again.
-- 5. Additional triggers capture fulfillment history, inbox/admin events, and Flash Sale reservations.

-- Meaning of amounts:
-- base_unit_price: regular price per transaction UOM.
-- unit_price: price after product discount and before cart discount.
-- fixed_amount on an item is a PER-UNIT reduction; on order_promotions it is a CART TOTAL reduction.
-- subtotal includes purchased regular amounts AND regular valuation of gifts.
-- product_discount_amount includes the full gift valuation.
-- total_quantity sums purchased transaction quantities and excludes gifts.
-- Current checkout writes zero tax, even though table constraints allow nonnegative tax.

