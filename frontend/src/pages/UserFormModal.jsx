import { useEffect, useState } from "react";
import { FiEye, FiEyeOff } from "react-icons/fi";
import API from "../api/api";

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function UserFormModal({ user, onClose, onSaved }) {
  const [email, setEmail] = useState(user?.email || "");
  const [fullName, setFullName] = useState(user?.full_name || "");
  const [password, setPassword] = useState("");
  const [roles, setRoles] = useState([]);
  const [selectedRole, setSelectedRole] = useState(user?.roles?.[0] || "");
  const [showPassword, setShowPassword] = useState(false);
  const [errors, setErrors] = useState({});
  const [submitError, setSubmitError] = useState("");

  useEffect(() => {
    setEmail(user?.email || "");
    setFullName(user?.full_name || "");
    setPassword("");
    setSelectedRole(user?.roles?.[0] || "");
    setShowPassword(false);
    setErrors({});
    setSubmitError("");
  }, [user]);

  useEffect(() => {
    API.get("/users/roles").then((res) => setRoles(res.data.roles));
  }, []);

  const validate = () => {
    const nextErrors = {};
    const trimmedEmail = email.trim();
    const trimmedFullName = fullName.trim();

    if (!user) {
      if (!trimmedEmail) {
        nextErrors.email = "Email is required";
      } else if (!EMAIL_REGEX.test(trimmedEmail)) {
        nextErrors.email = "Invalid email address";
      }
    }

    if (!trimmedFullName) {
      nextErrors.fullName = "Full name is required";
    }

    if (!user && !password) {
      nextErrors.password = "Password is required";
    }

    if (!selectedRole) {
      nextErrors.role = "Role is required";
    }

    setErrors(nextErrors);
    return Object.keys(nextErrors).length === 0;
  };

  const submit = async () => {
    setSubmitError("");

    if (!validate()) {
      return;
    }

    try {
      if (user) {
        await API.put(`/users/${user.id}`, {
          full_name: fullName.trim(),
          roles: [selectedRole],
          ...(password && { password }),
        });
      } else {
        await API.post("/users/create-user", {
          email: email.trim(),
          password,
          full_name: fullName.trim(),
          roles: [selectedRole],
        });
      }

      onSaved();
      onClose();
    } catch (err) {
      const message = err?.response?.data?.message || "Unable to save user";

      if (!user && (err?.response?.status === 409 || message === "User already exists")) {
        setErrors((prev) => ({ ...prev, email: "Email already exists." }));
      } else if (message.toLowerCase().includes("password")) {
        setErrors((prev) => ({ ...prev, password: message }));
      } else if (message.toLowerCase().includes("role")) {
        setErrors((prev) => ({ ...prev, role: message }));
      } else if (message.toLowerCase().includes("email")) {
        setErrors((prev) => ({ ...prev, email: message }));
      } else if (message.toLowerCase().includes("name")) {
        setErrors((prev) => ({ ...prev, fullName: message }));
      } else {
        setSubmitError(message);
      }
    }
  };

  return (
    <div className="modal show d-block">
      <div className="modal-dialog">
        <div className="modal-content">
          <div className="modal-header">
            <h5>{user ? "Edit User" : "Create User"}</h5>
            <button className="btn-close" onClick={onClose} />
          </div>

          <div className="modal-body">
            {submitError && <div className="alert alert-danger py-2">{submitError}</div>}

            <input
              className={`form-control mb-1 ${errors.email ? "is-invalid" : ""}`}
              placeholder="Email"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                setErrors((prev) => ({ ...prev, email: undefined }));
              }}
              disabled={!!user}
            />
            {errors.email && <div className="text-danger small mb-2">{errors.email}</div>}

            <input
              className={`form-control mb-1 ${errors.fullName ? "is-invalid" : ""}`}
              placeholder="Full Name"
              value={fullName}
              onChange={(e) => {
                setFullName(e.target.value);
                setErrors((prev) => ({ ...prev, fullName: undefined }));
              }}
            />
            {errors.fullName && <div className="text-danger small mb-2">{errors.fullName}</div>}

            <div className="position-relative mb-1">
              <input
                type={showPassword ? "text" : "password"}
                className={`form-control pe-5 ${errors.password ? "is-invalid" : ""}`}
                placeholder="Password"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  setErrors((prev) => ({ ...prev, password: undefined }));
                }}
              />
              <button
                type="button"
                className="btn btn-link position-absolute top-50 end-0 translate-middle-y text-muted text-decoration-none"
                onClick={() => setShowPassword((prev) => !prev)}
                aria-label={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? <FiEyeOff size={18} /> : <FiEye size={18} />}
              </button>
            </div>
            {errors.password && <div className="text-danger small mb-2">{errors.password}</div>}

            <select
              className={`form-control ${errors.role ? "is-invalid" : ""}`}
              value={selectedRole}
              onChange={(e) => {
                setSelectedRole(e.target.value);
                setErrors((prev) => ({ ...prev, role: undefined }));
              }}
            >
              <option value="">Select Role</option>
              {roles.map((r) => (
                <option key={r.id} value={r.name}>
                  {r.name}
                </option>
              ))}
            </select>
            {errors.role && <div className="text-danger small mt-1">{errors.role}</div>}
          </div>

          <div className="modal-footer">
            <button className="btn btn-secondary" onClick={onClose}>
              Back
            </button>
            <button className="btn btn-primary" onClick={submit}>
              Save
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
