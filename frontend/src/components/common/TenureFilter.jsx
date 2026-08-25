import { useEffect, useState } from "react";
import { FormControl, MenuItem, Select, InputLabel, TextField } from "@mui/material";
import dayjs from "dayjs";
export default function TenureFilter({ tenure, startDate, endDate, handleTenureChange, setStartDate, setEndDate }) {
  const [startDateInput, setStartDateInput] = useState(
    startDate.format("YYYY-MM-DD")
  );
  const [endDateInput, setEndDateInput] = useState(
    endDate.format("YYYY-MM-DD")
  );

  const parseManualDate = (value) => {
    if (!value) return null;
    const parsed = dayjs(value, ["YYYY-MM-DD", "DD/MM/YYYY"], true);
    return parsed.isValid() ? parsed : null;
  };

  const handleStartDateInputChange = (e) => {
    const value = e.target.value;
    setStartDateInput(value);
    const parsed = parseManualDate(value);
    if (parsed) {
      setStartDate(parsed);
    } else if (value === "") {
      setStartDate(null);
    }
  };

  const handleEndDateInputChange = (e) => {
    const value = e.target.value;
    setEndDateInput(value);
    const parsed = parseManualDate(value);
    if (parsed) {
      setEndDate(parsed);
    } else if (value === "") {
      setEndDate(null);
    }
  };

  useEffect(() => {
    setStartDateInput(startDate ? startDate.format("YYYY-MM-DD") : "");
    setEndDateInput(endDate ? endDate.format("YYYY-MM-DD") : "");
  }, [tenure, startDate, endDate]);

  return (
    <div className="row align-items-center mb-4">
      <div className="col-md-6 pb-3">
        <FormControl fullWidth size="small">
          <InputLabel>Select Tenure</InputLabel>
          <Select value={tenure} label="Select Tenure" onChange={handleTenureChange}>
            <MenuItem value="1m">Past 1 Month</MenuItem>
            <MenuItem value="3m">Past 3 Months</MenuItem>
            <MenuItem value="6m">Past 6 Months</MenuItem>
            <MenuItem value="1y">Past 1 Year</MenuItem>
            <MenuItem value="custom">Custom Date</MenuItem>
          </Select>
        </FormControl>
      </div>

      <div className="col-md-6 d-flex justify-content-md-end gap-2 mt-2 mt-md-0">
        {tenure === "custom" ? (
          <>
            <TextField
              type="date"
              size="small"
              label="Start Date"
              value={startDateInput}
              onChange={handleStartDateInputChange}
              onBlur={(e) => {
                const parsed = parseManualDate(e.target.value);
                if (parsed || e.target.value === "") {
                  setStartDate(parsed);
                  setStartDateInput(parsed ? parsed.format("YYYY-MM-DD") : "");
                }
              }}
            />
            <TextField
              type="date"
              size="small"
              label="End Date"
              value={endDateInput}
              onChange={handleEndDateInputChange}
              onBlur={(e) => {
                const parsed = parseManualDate(e.target.value);
                if (parsed || e.target.value === "") {
                  setEndDate(parsed);
                  setEndDateInput(parsed ? parsed.format("YYYY-MM-DD") : "");
                }
              }}
            />
          </>
        ) : (
          <div className="fw-bold small d-flex align-items-center gap-2">
            <span>{startDate.format("DD-MM-YYYY")}</span>
            <span>to</span>
            <span>{endDate.format("DD-MM-YYYY")}</span>
          </div>
        )}
      </div>
    </div>
  );
}
