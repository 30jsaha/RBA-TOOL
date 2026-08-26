import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { login, setAccessToken } from "../services/auth";
import { FiEye, FiEyeOff } from "react-icons/fi";
import "./css/Login.css";
import Logo from "../assets/img/logo.png";
import LoginBgNew from "../assets/img/login-bg-new-v2.jpg";

export default function Login() {
  const navigate = useNavigate();
  const [showPassword, setShowPassword] = useState(false);
  const [form, setForm] = useState({ email: "", password: "" });
  const [error, setError] = useState("");

  const handleChange = (e) =>
    setForm({ ...form, [e.target.name]: e.target.value });

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      const res = await login(form.email, form.password);

      if (res?.access) {
        navigate("/common-dashboard");
      } else {
        setError(res.message || "Unexpected response from server");
        setTimeout(() => setError(""), 2000);
      }
    } catch (err) {
      let msg = "Something went wrong";
      if (err.data && err.data.message) {
        msg = err.data.message;
      }
      setError(msg);
      setTimeout(() => setError(""), 2000);
    }
  };

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const access = params.get("access");

    if (access) {
      setAccessToken(access);
      window.history.replaceState({}, document.title, "/");
      navigate("/common-dashboard");
    }
  }, [navigate]);

  return (
    <div
      className="login-page"
      style={{ backgroundImage: `url(${LoginBgNew})` }}
    >
      <div className="login-logo">
        <img src={Logo} alt="Logo" />
      </div>

      <div className="d-flex align-items-center login-container">
        <div className="login-box">
          <div className="text-center mb-4 login-title">Login</div>

          {error && (
            <div className="alert alert-danger py-2" role="alert">
              {error}
            </div>
          )}

          <form onSubmit={handleSubmit}>
            <div className="mb-3 input-group d-flex flex-column">
              <label className="form-label">Email</label>
              <input
                required
                type="email"
                name="email"
                className="form-input-login w-100 form-control"
                value={form.email}
                onChange={handleChange}
              />
            </div>

            <div className="mb-3 input-group position-relative">
              <label className="form-label">Password</label>
              <div className="position-relative w-100">
                <input
                  required
                  type={showPassword ? "text" : "password"}
                  name="password"
                  className="form-input-login w-100 pe-5 form-control"
                  value={form.password}
                  onChange={handleChange}
                />
                <span
                  className="password-toggle-icon"
                  onClick={() => setShowPassword(!showPassword)}
                >
                  {showPassword ? <FiEyeOff size={18} /> : <FiEye size={18} />}
                </span>
              </div>
            </div>

            <button
              type="submit"
              className="w-100 login-button btn btn-primary"
            >
              Login Now
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
