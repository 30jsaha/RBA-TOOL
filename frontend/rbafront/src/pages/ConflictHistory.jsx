import { useEffect, useMemo, useState } from "react";
import Header from "../components/layout/Header";
import Sidebar from "../components/layout/Sidebar";
import Footer from "../components/layout/Footer";
import "./css/ConflictsList.css";
import "../styles/conflicts.css";
import API from "../api/api";
import Swal from "sweetalert2";
import ConflictTable from "../components/conflicts/ConflictTable";

export default function ConflictHistory() {
  const [conflicts, setConflicts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [taxType, setTaxType] = useState("");

  const [collapsed, setCollapsed] = useState(false);
  const [openMenu, setOpenMenu] = useState("settings");

  const params = useMemo(
    () => ({
      tax_type: taxType || undefined,
      status: "1,2",
    }),
    [taxType]
  );

  useEffect(() => {
    loadConflicts();
  }, [params]);

  const loadConflicts = async () => {
    try {
      setLoading(true);
      const res = await API.get("/admin/conflicts/history", { params });
      setConflicts(res.data.data || []);
    } catch (err) {
      Swal.fire({
        icon: "error",
        title: "Load Failed",
        text: err.response?.data?.message || "Failed to load conflicts",
      });
    } finally {
      setLoading(false);
    }
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
              <div className="header-title-page mb-3">Conflict History</div>

              <div className="card mb-3">
                <div className="card-body d-flex align-items-center gap-3">
                  <label className="mb-0 fw-bold">Tax Type:</label>
                  <select
                    className="form-select w-auto"
                    value={taxType}
                    onChange={(e) => setTaxType(e.target.value)}
                  >
                    <option value="">All</option>
                    <option value="GST">GST</option>
                    <option value="SWT">SWT</option>
                    <option value="CIT">CIT</option>
                  </select>
                </div>
              </div>

              <div className="card">
                <div className="card-header">
                  <h5 className="mb-0">Conflict History</h5>
                </div>

                <div className="card-body">
                  <ConflictTable
                    rows={conflicts}
                    loading={loading}
                    showActions={false}
                    showActionColumn={false}
                  />
                </div>
              </div>
            </div>
          </main>
        </div>

        <Footer />
      </div>
    </div>
  );
}
