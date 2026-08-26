import { Box, Typography } from "@mui/material";

const normalizeFraudReason = (text) =>
  String(text || "")
    .replace(/\\n/g, "\n")
    .replace(/\\u2022/g, "•")
    .replace(/â€¢/g, "•")
    .trim();

const buildSimpleList = (items) => [
  {
    title: null,
    items,
  },
];

const parseFraudReasonSections = (message) => {
  const normalized = normalizeFraudReason(message);
  if (!normalized) return [];

  if (normalized.includes("•")) {
    const parts = normalized
      .split("•")
      .map((item) => item.trim())
      .filter(Boolean);

    if (parts.length > 0) return buildSimpleList(parts);
  }

  if (!/\d+\.\s*/.test(normalized)) {
    const parts = normalized
      .split(";")
      .map((item) => item.trim())
      .filter(Boolean);

    if (parts.length > 0) return buildSimpleList(parts);
  }

  const blocks = normalized.split(/(?=\n?\d+\.\s*)/g);
  const sections = blocks
    .map((block) => {
      const titleMatch = block.match(/\d+\.\s*(?:Flag\s*-\s*)?([^:]+):/i);
      if (!titleMatch) return null;

      const title = titleMatch[1].trim();
      const details = block.slice(titleMatch[0].length).trim();
      const items = details
        .split(/\(\s*(?:i|ii|iii|iv|v|vi|vii|viii|ix|x)\s*\)/gi)
        .map((item) => item.trim())
        .filter(Boolean);

      return {
        title,
        items,
      };
    })
    .filter(Boolean);

  if (sections.length > 0) return sections;

  return buildSimpleList([normalized]);
};

export default function FraudReasonContent({ message, typographyVariant = "body1" }) {
  const sections = parseFraudReasonSections(message);

  if (sections.length === 0) {
    return <Typography variant={typographyVariant}>No details available.</Typography>;
  }

  return (
    <Box sx={{ fontSize: "15px", lineHeight: 1.6, color: "#333" }}>
      {sections.map((section, index) => (
        <Box key={`${section.title || "section"}-${index}`} sx={{ mb: index === sections.length - 1 ? 0 : 1.5 }}>
          {section.title ? (
            <Typography variant={typographyVariant} component="div" sx={{ fontWeight: 700, color: "#D2122E", mb: section.items.length ? 0.5 : 0 }}>
              {section.title}
            </Typography>
          ) : null}
          {section.items.length ? (
            <Box component="ul" sx={{ pl: 2.5, mb: 0, mt: 0 }}>
              {section.items.map((item, itemIndex) => (
                <Box component="li" key={`${index}-${itemIndex}`} sx={{ mb: 0.5 }}>
                  <Typography variant={typographyVariant} component="span">
                    {item}
                  </Typography>
                </Box>
              ))}
            </Box>
          ) : null}
        </Box>
      ))}
    </Box>
  );
}
