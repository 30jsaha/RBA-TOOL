import { useEffect, useState } from "react";
import Header from "../components/layout/Header";
import Sidebar from "../components/layout/Sidebar";
import Footer from "../components/layout/Footer";
import API from "../api/api";
import InvalidTinFormModal from "./InvalidTinFormModal";

export default function InvalidTins() {
  const [tins, setTins] = useState([]);
  const [open, setOpen] = useState(false);
  const [editTin, setEditTin] = useState(null);

  // layout states (same as other pages)
  const [collapsed, setCollapsed] = useState(false);
  const [openMenu, setOpenMenu] = useState("");

  const loadTins = async () => {
    const res = await API.get("/invalid-tins/list");
    setTins(res.data.data || []);
  };

  useEffect(() => {
    loadTins();
  }, []);

  const toggleStatus = async (id, status) => {
    try {
      await API.put(`/invalid-tins/${id}/status`, {
        status: !status,
      });

      // Optimistic UI update
      setTins((prev) =>
        prev.map((t) =>
          t.id === id ? { ...t, status: !status } : t
        )
      );
    } catch (err) {
      alert(err.response?.data?.message || "Action failed");
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
                Invalid TIN Management
              </div>

              {/* CARD */}
              <div className="card">
                <div className="card-header d-flex justify-content-between align-items-center">
                  <h5 className="mb-0">Invalid TINs</h5>
                  <button
                    className="btn btn-danger btn-sm"
                    onClick={() => setOpen(true)}
                  >
                    + Add Invalid TIN
                  </button>
                </div>

                <div className="card-body">
                  <div className="table-container">
                    <table className="table table-bordered table-striped">
                      <thead>
                        <tr>
                          <th>TIN Number</th>
                          <th>Status</th>
                          <th>Created Date</th>
                          <th style={{ width: "180px" }}>Action</th>
                        </tr>
                      </thead>
                      <tbody>
                        {tins.length === 0 ? (
                          <tr>
                            <td colSpan="4" className="text-center">
                              No invalid TINs found
                            </td>
                          </tr>
                        ) : (
                          tins.map((t) => (
                            <tr key={t.id}>
                              <td>{t.tin_number}</td>
                              <td>
                                <span
                                  className={`badge ${
                                    t.status ? "bg-success" : "bg-danger"
                                  }`}
                                >
                                  {t.status ? "Active" : "Inactive"}
                                </span>
                              </td>
                              <td>
                                {new Date(t.created_date).toLocaleString()}
                              </td>
                              <td>
                                <button
                                  className="btn btn-info btn-sm me-2"
                                  onClick={() => {
                                    setEditTin(t);
                                    setOpen(true);
                                  }}
                                >
                                  Edit
                                </button>

                                <button
                                  className="btn btn-warning btn-sm"
                                  onClick={() =>
                                    toggleStatus(t.id, t.status)
                                  }
                                >
                                  {t.status ? "Disable" : "Enable"}
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

        {/* FOOTER */}
        <Footer />
      </div>

      {/* CREATE / EDIT MODAL */}
      {open && (
        <InvalidTinFormModal
          tin={editTin}
          onClose={() => {
            setOpen(false);
            setEditTin(null);
          }}
          onSaved={loadTins}
        />
      )}
    </div>
  );
}
