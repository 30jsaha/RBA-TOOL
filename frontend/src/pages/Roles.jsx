import { useEffect, useState } from "react";
import Header from "../components/layout/Header";
import Sidebar from "../components/layout/Sidebar";
import Footer from "../components/layout/Footer";
import API from "../api/api";
import RoleFormModal from "./RoleFormModal";

export default function Roles() {
  const [roles, setRoles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);
  const [editRole, setEditRole] = useState(null);
  const [collapsed, setCollapsed] = useState(false);
  const [openMenu, setOpenMenu] = useState("");

  const loadRoles = async () => {
    try {
      setError("");
      setLoading(true);
      const res = await API.get("/roles");
      setRoles(Array.isArray(res?.data?.roles) ? res.data.roles : []);
    } catch (err) {
      setError(err?.response?.data?.message || "Failed to load roles");
      setRoles([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadRoles();
  }, []);

  const saveRole = async (name) => {
    if (editRole) {
      await API.put(`/roles/${editRole.id}`, { name });
    } else {
      await API.post("/roles", { name });
    }
    await loadRoles();
  };

  return (
    <div className="container-fluid">
      <div className="row">
        <Header toggleSidebar={() => setCollapsed(!collapsed)} />

        <div className="col-lg-12">
          <Sidebar
            collapsed={collapsed}
            setCollapsed={setCollapsed}
            openMenu={openMenu}
            setOpenMenu={setOpenMenu}
          />

          <main className="main-content mt-5">
            <div className="container-fluid">
              <div className="header-title-page mb-3">Role Master</div>

              <div className="card">
                <div className="card-header d-flex justify-content-between align-items-center">
                  <h5 className="mb-0">Roles</h5>
                  <button
                    className="btn btn-danger btn-sm"
                    onClick={() => {
                      setEditRole(null);
                      setOpen(true);
                    }}
                  >
                    + Create Role
                  </button>
                </div>

                <div className="card-body">
                  {error && <div className="alert alert-danger py-2">{error}</div>}

                  <div className="table-container">
                    <table className="table table-bordered table-striped">
                      <thead>
                        <tr>
                          <th style={{ width: "90px" }}>ID</th>
                          <th>Role Name</th>
                          <th style={{ width: "140px" }}>Users</th>
                          <th style={{ width: "180px" }}>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {loading ? (
                          <tr>
                            <td colSpan="4" className="text-center">Loading roles...</td>
                          </tr>
                        ) : roles.length === 0 ? (
                          <tr>
                            <td colSpan="4" className="text-center">No roles found</td>
                          </tr>
                        ) : (
                          roles.map((role) => (
                            <tr key={role.id}>
                              <td>{role.id}</td>
                              <td>
                                <div className="d-flex align-items-center gap-2">
                                  <span>{role.name}</span>
                                  {role.is_system && <span className="badge bg-secondary">System</span>}
                                </div>
                              </td>
                              <td>{role.user_count ?? 0}</td>
                              <td>
                                <button
                                  className="btn btn-info btn-sm"
                                  onClick={() => {
                                    setEditRole(role);
                                    setOpen(true);
                                  }}
                                >
                                  Edit
                                </button>
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

        <Footer />
      </div>

      {open && (
        <RoleFormModal
          role={editRole}
          onClose={() => {
            setOpen(false);
            setEditRole(null);
          }}
          onSaved={saveRole}
        />
      )}
    </div>
  );
}
