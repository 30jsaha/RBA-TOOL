const MAX_COMPACT_DECIMALS = 2;

const trimTrailingZeroes = (value) => value.replace(/\.0+$/, "").replace(/(\.\d*?)0+$/, "$1");

/**
 * Formats monetary ApexCharts axis values as Papua New Guinea Kina.
 * Invalid values are returned blank so ApexCharts does not display misleading data.
 */
export const formatKinaAxisValue = (value) => {
  if (value === null || value === undefined || value === "") {
    return "";
  }

  const numericValue = Number(value);
  if (!Number.isFinite(numericValue)) {
    return "";
  }

  const absoluteValue = Math.abs(numericValue);
  let formattedValue;

  if (absoluteValue >= 1_000_000_000) {
    formattedValue = trimTrailingZeroes((numericValue / 1_000_000_000).toFixed(MAX_COMPACT_DECIMALS)) + "B";
  } else if (absoluteValue >= 1_000_000) {
    formattedValue = trimTrailingZeroes((numericValue / 1_000_000).toFixed(MAX_COMPACT_DECIMALS)) + "M";
  } else {
    formattedValue = numericValue.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }

  return `K ${formattedValue}`;
};
