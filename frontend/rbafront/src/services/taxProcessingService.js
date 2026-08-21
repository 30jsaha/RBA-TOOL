import axios from "axios";
const API_BASE = import.meta.env.VITE_API_BASE_URL;
export const getAxiosInstance = (taxType, accessToken) => {
  const BASE =
    taxType === "gst"
      ? `${API_BASE}/gst/process`
      : taxType === "swt"
      ? `${API_BASE}/swt/process`
      : `${API_BASE}/cit/process`;

  return axios.create({
    baseURL: BASE,
    headers: { Authorization: accessToken ? `Bearer ${accessToken}` : "" },
  });
};

export const uploadTaxFile = (axiosInstance, taxType, file) => {
  const formData = new FormData();
  formData.append("file", file);

  const uploadAPI =
    taxType === "gst"
      ? "/upload-gst"
      : taxType === "swt"
      ? "/upload-swt"
      : "/upload-cit";

  return axiosInstance.post(uploadAPI, formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
};

export const processTaxSteps = async (axiosInstance, taxType, uploadResponse) => {
  const file_upload_history_id = uploadResponse.file_upload_history_id;
  const upload_path = uploadResponse.upload_path;

  const steps =
    taxType === "gst"
      ? [
          "/validate-and-clean-gst-data",
          "/restore-taxpayers-gst",
          "/segmentation-gst",
          "/prediction-gst",
          "/process-flags-gst",
        ]
      : taxType === "swt"
      ? [
          "/validate-and-clean-swt-data",
          "/restore-taxpayers-swt",
          "/segmentation-swt",
          "/prediction-swt",
          "/process-flags-swt",
        ]
      : [
          "/validate-and-clean-cit-data",
          "/restore-taxpayers-cit",
          "/segmentation-cit",
          "/prediction-cit",
          "/process-flags-cit",
        ];

  // Step 1
  const clean = await axiosInstance.post(steps[0], {
    file_upload_history_id,
    upload_path,
  });

  // Step 2
  const restore = await axiosInstance.post(steps[1], {
    cleaned_file: clean.data.cleaned_file,
    file_upload_history_id,
  });

  // Step 3
  const segment = await axiosInstance.post(steps[2], {
    restored_file: restore.data.restored_file,
    file_upload_history_id,
  });

  // Step 4
  const predict = await axiosInstance.post(steps[3], {
    segmented_file: segment.data.segmented_file,
    file_upload_history_id,
  });

  // Step 5
  await axiosInstance.post(steps[4], {
    predicted_file: predict.data.predicted_file || predict.data.prediction_file,
    file_upload_history_id,
  });

  return true;
};

export const fetchMergedDetails = (axiosInstance) => {
  return axiosInstance.get("/details");
};