import { useEffect, useState } from "react";
import Header from "../components/layout/Header";
import Sidebar from "../components/layout/Sidebar";
import Footer from "../components/layout/Footer";
import API from "../api/api";
import UserFormModal from "./UserFormModal";

export default function Users() {
  const [users, setUsers] = useState([]);
  const [open, setOpen] = useState(false);
  const [editUser, setEditUser] = useState(null);

  // layout states (same as UploadHistory)
  const [collapsed, setCollapsed] = useState(false);
  const [openMenu, setOpenMenu] = useState("");

  const loadUsers = async () => {
    try {
      const res = await API.get("/users/list");
      const data = res?.data || {};
      setUsers(Array.isArray(data.users) ? data.users : []);
    } catch (err) {
      console.error("Failed to load users:", err.response?.data || err.message);
      setUsers([]);
    }
  };

  useEffect(() => {
    loadUsers();
  }, []);

  const toggleStatus = async (id, is_active) => {
  try {
    console.log("Toggling status for user:", id, "current:", is_active);
    const res = await API.put(`/users/${id}/status`, {
      is_active: !is_active,
    });
    console.log("Status updated:", res.data);
    loadUsers();
  } catch (err) {
    console.error("Disable failed:", err.response?.data || err.message);
    alert(err.response?.data?.message || "Disable failed");
  }
};


  return (
    <div className="container-fluid">
      <div className="row">
        {/* HEADER */}
        <Header toggleSidebar={() => setCollapsed(!collapsed)} />

        {/* SIDEBAR + CONTENT */}
        <div className="col-lg-12">
          <Sidebar
            collapsed={collapsed}
            setCollapsed={setCollapsed}
            openMenu={openMenu}
            setOpenMenu={setOpenMenu}
          />

          <main className="main-content mt-5">
            <div className="container-fluid">
              {/* PAGE TITLE */}
              <div className="header-title-page mb-3">
                User Management
              </div>

              {/* CARD */}
              <div className="card">
                <div className="card-header d-flex justify-content-between align-items-center">
                  <h5 className="mb-0">Users</h5>
                  <button
                    className="btn btn-danger btn-sm"
                    onClick={() => setOpen(true)}
                  >
                    + Create User
                  </button>
                </div>

                <div className="card-body">
                  <div className="table-container">
                    <table className="table table-bordered table-striped">
                      <thead>
                        <tr>
                          <th>Full Name</th>
                          <th>Roles</th>
                          <th>Status</th>
                          <th style={{ width: "180px" }}>Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {users.length === 0 ? (
                          <tr>
                            <td colSpan="4" className="text-center">
                              No users found
                            </td>
                          </tr>
                        ) : (
                          users.map((u) => (
                            <tr key={u.id}>
                              <td>{u.full_name}</td>
                              <td>{u.roles.join(", ")}</td>
                              <td>
                                <span
                                  className={`badge ${
                                    u.is_active ? "bg-success" : "bg-danger"
                                  }`}
                                >
                                  {u.is_active ? "Active" : "Disabled"}
                                </span>
                              </td>
                              <td>
                                <button
                                  className="btn btn-info btn-sm me-2"
                                  onClick={() => {
                                    setEditUser(u);
                                    setOpen(true);
                                  }}
                                >
                                  Edit
                                </button>
                                    {!u.roles.includes("ADMIN") && (
                                    <button
                                        className="btn btn-warning btn-sm"
                                        onClick={() => toggleStatus(u.id, u.is_active)}
                                    >
                                        {u.is_active ? "Disable" : "Enable"}
                                    </button>
                                    )}
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            </div>
          </main>
        </div>

        {/* FOOTER */}
        <Footer />
      </div>

      {/* CREATE / EDIT MODAL */}
      {open && (
        <UserFormModal
          user={editUser}
          onClose={() => {
            setOpen(false);
            setEditUser(null);
          }}
          onSaved={loadUsers}
        />
      )}
    </div>
  );
}
