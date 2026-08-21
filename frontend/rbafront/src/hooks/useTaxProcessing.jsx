import { useState } from "react";
import { getAxiosInstance, uploadTaxFile, processTaxSteps, fetchMergedDetails } from "../services/taxProcessingService";

export default function useTaxProcessing() {
  const [uploadResponse, setUploadResponse] = useState(null);
  const [progress, setProgress] = useState(0);
  const [processing, setProcessing] = useState(false);
  const [statusMsg, setStatusMsg] = useState("");

  const accessToken = localStorage.getItem("access");

  const startUpload = async (taxType, file) => {
    const axiosInstance = getAxiosInstance(taxType, accessToken);
    const res = await uploadTaxFile(axiosInstance, taxType, file);
    setUploadResponse(res.data);
    return res.data;
  };

  const startProcessing = async (taxType) => {
    if (!uploadResponse) throw new Error("Upload file first.");

    setProcessing(true);
    setProgress(10);
    setStatusMsg(`Validating ${taxType.toUpperCase()} data...`);

    const axiosInstance = getAxiosInstance(taxType, accessToken);
    await processTaxSteps(axiosInstance, taxType, uploadResponse);

    setProgress(100);
    setStatusMsg("Completed!");
    setProcessing(false);
  };

  const loadMerged = async (taxType) => {
    const axiosInstance = getAxiosInstance(taxType, accessToken);
    const response = await fetchMergedDetails(axiosInstance);
    return response.data;
  };

  return {
    uploadResponse,
    progress,
    processing,
    statusMsg,
    startUpload,
    startProcessing,
    loadMerged,
  };
}