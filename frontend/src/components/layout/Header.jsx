import AvtarImage from "../../assets/user/avatar-8.jpg";
import { IoMdLogOut } from "react-icons/io";

import { useAuth } from "../../context/useAuth";

export default function Header() {
  const { logout } = useAuth();

  const handleLogout = async () => {
    await logout();
    window.location.href = "/";
  };

  return (
    <nav className="navbar navbar-expand-lg navbar-dark bg-navbar fixed-top header">
      <div className="container-fluid">
        <div className="ms-auto d-flex align-items-center">
          <img
            src={AvtarImage}
            alt="Admin"
            className="rounded-circle me-3"
            width="40"
            height="40"
          />
          <button
            className="btn btn-secondary btn-sm logout-btn"
            alt="Logout"
            onClick={handleLogout}
          >
            <i className="bi bi-box-arrow-right me-1"></i> <IoMdLogOut />
          </button>
        </div>
      </div>
    </nav>
  );
}

