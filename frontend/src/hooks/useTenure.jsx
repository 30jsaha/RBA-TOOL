import { useState } from "react";
import dayjs from "dayjs";

export default function useTenure(defaultValue = "1m") {
  const [tenure, setTenure] = useState(defaultValue);
  const [startDate, setStartDate] = useState(dayjs().startOf("month"));
  const [endDate, setEndDate] = useState(dayjs().endOf("month"));

  const handleTenureChange = (e) => {
    const val = e.target.value;
    setTenure(val);

    const today = dayjs();
    let start, end;

    switch (val) {
      case "1m":
        start = today.subtract(1, "month").startOf("month");
        end = today.subtract(1, "month").endOf("month");
        break;
      case "3m":
        start = today.subtract(3, "month").startOf("month");
        end = today.endOf("month");
        break;
      case "6m":
        start = today.subtract(6, "month").startOf("month");
        end = today.endOf("month");
        break;
      case "1y":
        start = today.subtract(1, "year").startOf("month");
        end = today.endOf("month");
        break;
      case "custom":
      default:
        return;
    }

    setStartDate(start);
    setEndDate(end);
  };

  return {
    tenure,
    startDate,
    endDate,
    setStartDate,
    setEndDate,
    handleTenureChange,
    setTenure, // optional
  };
}