const SUPPORT_OPTIONS = [
  {
    id: "call_now",
    label: "Call Now",
    description: "Talk to a support representative.",
    href: "/under-development?source=call_now",
  },
  {
    id: "email_support",
    label: "Email Support",
    description: "Send your question to support.",
    href: "/under-development?source=email_support",
  },
] as const;

type Props = {
  intro?: string;
};

export default function TicketSupportFallback({
  intro = "If you have questions or want to appeal this decision, contact Shopward Support.",
}: Props) {
  return (
    <div className="ticket-support-fallback">
      <p>{intro}</p>
      <div className="contact-support-actions">
        {SUPPORT_OPTIONS.map((option) => (
          <a key={option.id} className="contact-support-button" href={option.href}>
            <span>{option.label}</span>
            <small>{option.description}</small>
          </a>
        ))}
      </div>
    </div>
  );
}
