import { getPolicySectionTitle, parsePolicyContent, policyPreviewText } from "../lib/policyContent";

type Props = {
  sectionTitle: string;
  content: string;
  expanded: boolean;
};

export default function PolicySectionContent({ sectionTitle, content, expanded }: Props) {
  const displayTitle = getPolicySectionTitle(sectionTitle);

  if (!expanded) {
    return <p className="policy-section-content-preview">{policyPreviewText(content, displayTitle)}</p>;
  }

  const blocks = parsePolicyContent(content, displayTitle);

  return (
    <div className="policy-section-body">
      <div className="policy-section-body-content">
        {blocks.map((block, index) => {
          if (block.type === "heading") {
            const Tag = block.level === 3 ? "h5" : "h4";
            return (
              <Tag key={`${block.type}-${index}`} className="policy-section-subheading">
                {block.text}
              </Tag>
            );
          }

          if (block.type === "list") {
            return (
              <ul key={`${block.type}-${index}`} className="policy-section-list-items">
                {block.items.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            );
          }

          return (
            <p key={`${block.type}-${index}`} className="policy-section-paragraph">
              {block.text}
            </p>
          );
        })}
      </div>
    </div>
  );
}
