type Props = {
  compact?: boolean;
  className?: string;
};

export default function BrandLogo({ compact = false, className = "" }: Props) {
  return (
    <img
      src="/shopward-logo.png"
      alt="Shopward Customer Portal"
      className={`brand-logo ${compact ? "brand-logo-compact" : ""} ${className}`.trim()}
    />
  );
}
