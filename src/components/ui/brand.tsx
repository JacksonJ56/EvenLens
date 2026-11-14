import { Aperture, MessageSquare } from "lucide-react";

export function BrandMark({ assistant = false }: { assistant?: boolean }) {
  const Icon = assistant ? MessageSquare : Aperture;
  return <span className="brand-mark"><Icon size={20} strokeWidth={1.8} aria-hidden="true" /></span>;
}
