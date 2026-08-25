import dayjs from "dayjs";
import API from "../api/api";

export const processConflictData = async ({
  taxType,
  upload_path,
  file_upload_history_id,
  startDate,
  endDate,
  validRecords = 0,
  helpers,
}) => {
  const {
    setProgress,
    setStatusMsg,
    setError,
    showAlert,
    showConfirm,
    confirmConflictProceed,
    setProcessing,
    setInfo,
  } = helpers;

  const BASE_PATH =
    taxType === "gst"
      ? "/process"
      : taxType === "swt"
      ? "/swt/process"
      : "/cit/process";

  try {
    setProcessing(true);
    setError(null);

    // ===============================
    // CIT FLOW
    // ===============================
    if (taxType === "cit") {
      let flags_file = null;
      let citMultiTaxSkipped = false;

      setStatusMsg("Step 1: Validating & Cleaning CIT...");
      const cleanRes = await API.post("/cit/process/validate-and-clean-cit", {
        upload_path,
        file_upload_history_id,
      });

      const cleaned_file = cleanRes.data.files.preprocessed;
      setProgress(35);

      setStatusMsg("Step 2: Running Prediction...");
      const predRes = await API.post("/cit/process/prediction-cit", {
        cleaned_file,
        file_upload_history_id,
      });

      const predicted_file = predRes.data.prediction_file;
      setProgress(60);

      const citConflicts = Number(predRes.data.temp_changes_detected ?? 0);
      const proceedCit = await confirmConflictProceed(
        citConflicts,
        validRecords
      );
      if (!proceedCit) {
        setStatusMsg("Processing stopped due to financial record differences.");
        setProcessing(false);
        return false;
      }

      setStatusMsg("Step 3: Processing Flags...");
      const flagRes = await API.post("/cit/process/process-flags-cit", {
        predicted_file,
        file_upload_history_id,
      });

      flags_file = flagRes.data.flags_file;
      setProgress(80);

      // ===============================
      // STEP 4 — MULTITAX (OPTIONAL)
      // ===============================
      setStatusMsg("Step 4: Final Fraud Integration...");
      const financial_year_start = dayjs(startDate).year();
      const financial_year_end = dayjs(endDate).year();

      try {
        await API.post("/cit/process/process-multitax-cit", {
          flags_file,
          file_upload_history_id,
          financial_year_start,
          financial_year_end,
        });
      } catch (err) {
        const confirmSkip = await showConfirm(
          "Multi-Tax Not Found",
          "GST / SWT financial files were not found for the selected period.\n\nDo you want to skip Multi-Tax integration and complete CIT processing only?"
        );

        if (!confirmSkip.isConfirmed) {
          throw err;
        }

        citMultiTaxSkipped = true;
        setStatusMsg("⚠ Multi-Tax skipped. Completing CIT only...");
      }

      setProgress(100);
      setStatusMsg("✔ CIT Processing completed!");

      const successMsg = citMultiTaxSkipped
        ? "CIT processing completed. Multi-Tax (GST/SWT) was skipped due to missing financial data."
        : "CIT processing completed successfully.";

      setInfo?.(successMsg);
      await showAlert("success", "Success", successMsg);
      return true;
    }

    // ===============================
    // GST FLOW
    // ===============================
    if (taxType === "gst") {
      setStatusMsg("Step 1: Validating & Cleaning GST...");
      const cleanRes = await API.post(BASE_PATH + "/validate-and-clean-gst-data", {
        upload_path,
        file_upload_history_id,
      });

      const cleaned_file = cleanRes.data.cleaned_file;
      setProgress(35);

      setStatusMsg("Step 2: Running Prediction...");
      const predRes = await API.post(BASE_PATH + "/prediction", {
        cleaned_file,
        file_upload_history_id,
      });

      const predicted_file =
        predRes.data.predicted_file || predRes.data.prediction_file;
      setProgress(90);

      const gstConflicts = Number(predRes.data.total_structural_changes ?? 0);
      const proceedGst = await confirmConflictProceed(
        gstConflicts,
        validRecords
      );
      if (!proceedGst) {
        setStatusMsg("Processing stopped due to financial record differences.");
        setProcessing(false);
        return false;
      }

      setStatusMsg("Step 3: Processing Flags...");
      await API.post(BASE_PATH + "/process-flags", {
        prediction_file: predicted_file,
        file_history_id: file_upload_history_id,
      });

      setProgress(100);
      setStatusMsg("GST Processing completed!");
      const successMsg = "GST processing completed successfully.";
      setInfo?.(successMsg);
      await showAlert("success", "Success", successMsg);
      return true;
    }

    // ===============================
    // SWT FLOW
    // ===============================
    if (taxType === "swt") {
      setStatusMsg("Step 1: Validating & Cleaning SWT...");
      const cleanRes = await API.post(BASE_PATH + "/validate-and-clean-swt-data", {
        upload_path,
        file_upload_history_id,
      });

      const cleaned_file = cleanRes.data.cleaned_file;
      setProgress(35);

      setStatusMsg("Step 2: Feature Engineering...");
      const restoreRes = await API.post(BASE_PATH + "/feature-engineering-swt", {
        cleaned_file,
        file_upload_history_id,
      });

      const featured_file = restoreRes.data.featured_file;
      setProgress(55);

      setStatusMsg("Step 4: Running Prediction...");
      const predRes = await API.post(BASE_PATH + "/prediction-swt", {
        featured_file,
        file_upload_history_id,
      });

      const predicted_file = predRes.data.predicted_file;
      setProgress(90);

      const swtConflicts = Number(predRes.data.temp_changes_inserted ?? 0);
      const proceedSwt = await confirmConflictProceed(
        swtConflicts,
        validRecords
      );
      if (!proceedSwt) {
        setStatusMsg("Processing stopped due to financial record differences.");
        setProcessing(false);
        return false;
      }

      setStatusMsg("Step 5: Processing Flags...");
      await API.post(BASE_PATH + "/process-flags-swt", {
        predicted_file,
        file_upload_history_id,
      });

      setProgress(100);
      setStatusMsg("SWT Processing completed!");
      const successMsg = "SWT processing completed successfully.";
      setInfo?.(successMsg);
      await showAlert("success", "Success", successMsg);
      return true;
    }
  } catch (err) {
    setError(err.response?.data?.message || err.message);
    showAlert("error", "Processing Failed", err.message);
    return false;
  } finally {
    setProcessing(false);
  }
};
