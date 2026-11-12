"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";

import { Dialog } from "@/components/ui/dialog";
import { Alert, Button, errorMessage, Field, Input } from "@/components/ui/form";
import { api, ApiError } from "@/lib/api";
import type { IdentifierCheck, Product } from "@/lib/types";

function useIdentifierCheck(orgId: string, identifier: string) {
  const [check, setCheck] = useState<IdentifierCheck | null>(null);
  useEffect(() => {
    const value = identifier.trim();
    if (!value) return;
    let cancelled = false;
    const timer = setTimeout(() => {
      api<IdentifierCheck[]>("/products/validate", {
        method: "POST",
        orgId,
        body: { items: [{ identifier: value }] },
      })
        .then(([result]) => {
          if (!cancelled && result) setCheck(result);
        })
        .catch(() => {
          // Live check is a convenience; the create request validates again.
        });
    }, 350);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [orgId, identifier]);
  return identifier.trim() && check?.input === identifier.trim() ? check : null;
}

export function AddProductDialog({ orgId, open, onClose }: { orgId: string; open: boolean; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [identifier, setIdentifier] = useState("");
  const check = useIdentifierCheck(orgId, identifier);

  const create = useMutation({
    mutationFn: (body: { identifier: string; product_name: string; brand_name: string }) =>
      api<Product>("/products", { method: "POST", orgId, body }),
    onSuccess: async () => {
      setIdentifier("");
      await queryClient.invalidateQueries({ queryKey: ["tenant", orgId] });
      onClose();
    },
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    create.mutate({
      identifier,
      product_name: String(form.get("product_name") ?? ""),
      brand_name: String(form.get("brand_name") ?? ""),
    });
  }

  const duplicate = check?.existing_product_id != null;
  const createError =
    create.error instanceof ApiError && create.error.code === "plan_limit_reached"
      ? `${create.error.message} Remove products or upgrade your plan.`
      : create.error && errorMessage(create.error);

  return (
    <Dialog
      open={open}
      title="Add product"
      onClose={() => {
        create.reset();
        onClose();
      }}
    >
      <form onSubmit={submit} className="space-y-4">
        {createError && <Alert>{createError}</Alert>}
        <Field label="ASIN or Amazon.in product link" htmlFor="identifier">
          <Input
            id="identifier"
            name="identifier"
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
            placeholder="B0CHX1W1XY or https://www.amazon.in/dp/…"
            autoComplete="off"
            required
          />
        </Field>
        {check && (
          <div aria-live="polite" className="text-sm">
            {!check.valid && <p className="text-red-700 dark:text-red-400">{check.message}</p>}
            {check.valid && !duplicate && (
              <p className="text-green-700 dark:text-green-400">
                ASIN <strong>{check.normalized}</strong> looks valid. It will be confirmed on Amazon.in when it is first scanned.
              </p>
            )}
            {duplicate && (
              <p className="text-red-700 dark:text-red-400">{check.normalized} is already in your products.</p>
            )}
            {check.warning_messages.map((w) => (
              <p key={w} className="mt-1 text-amber-700 dark:text-amber-400">
                {w}
              </p>
            ))}
          </div>
        )}
        <Field label="Product name (optional)" htmlFor="product_name">
          <Input id="product_name" name="product_name" maxLength={300} />
        </Field>
        <Field label="Brand (optional)" htmlFor="brand_name">
          <Input id="brand_name" name="brand_name" maxLength={120} />
        </Field>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" disabled={create.isPending || duplicate || (check !== null && !check.valid)}>
            {create.isPending ? "Adding…" : "Add product"}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

export function EditProductDialog({ orgId, product, onClose }: {
  orgId: string;
  product: Product | null;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const update = useMutation({
    mutationFn: (body: { product_name: string; brand_name: string; monitoring_enabled: boolean }) =>
      api<Product>(`/products/${product?.id}`, { method: "PATCH", orgId, body }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["tenant", orgId] });
      onClose();
    },
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    update.mutate({
      product_name: String(form.get("product_name") ?? ""),
      brand_name: String(form.get("brand_name") ?? ""),
      monitoring_enabled: form.get("monitoring_enabled") === "on",
    });
  }

  return (
    <Dialog open={product !== null} title={`Edit ${product?.external_id ?? ""}`} onClose={onClose}>
      {product && (
        <form onSubmit={submit} className="space-y-4">
          {update.error && <Alert>{errorMessage(update.error)}</Alert>}
          <Field label="Product name" htmlFor="edit_product_name">
            <Input id="edit_product_name" name="product_name" defaultValue={product.product_name ?? ""} maxLength={300} />
          </Field>
          <Field label="Brand" htmlFor="edit_brand_name">
            <Input id="edit_brand_name" name="brand_name" defaultValue={product.brand_name ?? ""} maxLength={120} />
          </Field>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" name="monitoring_enabled" defaultChecked={product.monitoring_enabled} />
            Monitor this product (include in scheduled scans)
          </label>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button type="submit" disabled={update.isPending}>
              Save
            </Button>
          </div>
        </form>
      )}
    </Dialog>
  );
}
