import API from "../api/api";

export function fetchBusinessDecisionHistory(tin, params = {}) {
  return API.get(`/invalid-tins/${encodeURIComponent(tin)}/business-decisions`, { params });
}

export function fetchBusinessDecisionJob(jobId) {
  return API.get(`/invalid-tins/jobs/${encodeURIComponent(jobId)}`);
}

export function submitBusinessDecisionOverride(taxType, sourceRecordId, payload) {
  return API.post(
    `/invalid-tins/${encodeURIComponent(taxType)}/${encodeURIComponent(sourceRecordId)}/business-decisions/override`,
    payload
  );
}
