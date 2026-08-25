import axios from "axios";

const API_URL = "http://127.0.0.1:5000/api/auth";

export async function login(email, password) {
  try {
    const res = await axios.post(`${API_URL}/login`, { email, password });
    console.log("LOGIN RESPONSE:", res.data);
    return res.data;
  } catch (err) {
    if (err.response) {
      console.error("LOGIN ERROR:", err.response.data);
      throw err.response; // Pass backend error to caller
    } else {
      console.error("NETWORK ERROR:", err.message);
      throw err;
    }
  }
}
