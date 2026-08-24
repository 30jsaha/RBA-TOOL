import { useEffect, useMemo, useRef, useState } from "react";
import Header from "../components/layout/Header";
import Sidebar from "../components/layout/Sidebar";
import Footer from "../components/layout/Footer";
import API from "../api/api";
import { fetchCurrentUser } from "../services/auth";

function collectDescendantIds(node) {
  const ids = [node.id];
  (node.children || []).forEach((child) => {
    ids.push(...collectDescendantIds(child));
  });
  return ids;
}

function normalizeParentSelections(nodes, initialSelection) {
  const nextSelection = new Set(initialSelection);

  const walk = (node) => {
    const children = Array.isArray(node.children) ? node.children : [];
    if (children.length === 0) {
      return { full: nextSelection.has(node.id), partial: false };
    }

    const childStates = children.map(walk);
    const allChildrenFull = childStates.every((state) => state.full);
    const anyChildSelected = childStates.some((state) => state.full || state.partial);

    if (allChildrenFull) {
      nextSelection.add(node.id);
      return { full: true, partial: false };
    }

    nextSelection.delete(node.id);
    return { full: false, partial: anyChildSelected };
  };

  nodes.forEach(walk);
  return nextSelection;
}

function getNodeVisualState(node, selectedSet) {
  const children = Array.isArray(node.children) ? node.children : [];
  if (children.length === 0) {
    return { checked: selectedSet.has(node.id), indeterminate: false };
  }

  const childStates = children.map((child) => getNodeVisualState(child, selectedSet));
  const allChildrenChecked = childStates.every((state) => state.checked);
  const anyChildSelected = childStates.some((state) => state.checked || state.indeterminate);

  return {
    checked: selectedSet.has(node.id) && allChildrenChecked,
    indeterminate: !allChildrenChecked && anyChildSelected,
  };
}

function PermissionNode({ node, selectedSet, onToggle, level = 0 }) {
  const checkboxRef = useRef(null);
  const state = getNodeVisualState(node, selectedSet);

  useEffect(() => {
    if (checkboxRef.current) {
      checkboxRef.current.indeterminate = state.indeterminate;
    }
  }, [state.indeterminate]);

  return (
    <div style={{ marginLeft: level * 18 }}>
      <label className="form-check d-flex align-items-center gap-2 mb-2">
        <input
          ref={checkboxRef}
          type="checkbox"
          className="form-check-input"
          checked={state.checked}
          onChange={(e) => onToggle(node, e.target.checked)}
        />
        <span>
          <strong>{node.name}</strong>
          <span className="text-muted small ms-2">{node.code}</span>
        </span>
      </label>

      {(node.children || []).length > 0 && (
        <div className="mb-2">
          {node.children.map((child) => (
            <PermissionNode key={child.id} node={child} selectedSet={selectedSet} onToggle={onToggle} level={level + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

export default function RolePermissions() {
  const [roles, setRoles] = useState([]);
  const [permissions, setPermissions] = useState([]);
  const [selectedRoleId, setSelectedRoleId] = useState("");
  const [selectedPermissionIds, setSelectedPermissionIds] = useState(new Set());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [collapsed, setCollapsed] = useState(false);
  const [openMenu, setOpenMenu] = useState("");

  const permissionMap = useMemo(() => {
    const map = new Map();
    const walk = (items) => {
      (items || []).forEach((item) => {
        map.set(item.id, item);
        walk(item.children || []);
      });
    };
    walk(permissions);
    return map;
  }, [permissions]);

  const loadInitialData = async () => {
    try {
      setLoading(true);
      setError("");
      const [rolesRes, permissionsRes] = await Promise.all([API.get("/roles"), API.get("/permissions")]);
      const roleItems = Array.isArray(rolesRes?.data?.roles) ? rolesRes.data.roles : [];
      const permissionItems = Array.isArray(permissionsRes?.data?.permissions) ? permissionsRes.data.permissions : [];
      setRoles(roleItems);
      setPermissions(permissionItems);
      if (roleItems.length > 0) {
        setSelectedRoleId(String(roleItems[0].id));
      }
    } catch (err) {
      setError(err?.response?.data?.message || "Failed to load role permissions");
      setRoles([]);
      setPermissions([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadInitialData();
  }, []);

  useEffect(() => {
    if (!selectedRoleId) {
      setSelectedPermissionIds(new Set());
      return;
    }

    let active = true;
    setError("");
    setSuccess("");

    API.get(`/roles/${selectedRoleId}/permissions`)
      .then((res) => {
        if (!active) return;
        const ids = Array.isArray(res?.data?.permission_ids) ? res.data.permission_ids : [];
        setSelectedPermissionIds(normalizeParentSelections(permissions, new Set(ids)));
      })
      .catch((err) => {
        if (!active) return;
        setError(err?.response?.data?.message || "Failed to load role permissions");
        setSelectedPermissionIds(new Set());
      });

    return () => {
      active = false;
    };
  }, [selectedRoleId, permissions]);

  const handleToggle = (node, checked) => {
    setSelectedPermissionIds((current) => {
      const next = new Set(current);
      const descendantIds = collectDescendantIds(node);

      descendantIds.forEach((id) => {
        if (checked) {
          next.add(id);
        } else {
          next.delete(id);
        }
      });

      return normalizeParentSelections(permissions, next);
    });
  };

  const savePermissions = async () => {
    if (!selectedRoleId) return;

    setSaving(true);
    setError("");
    setSuccess("");

    try {
      await API.put(`/roles/${selectedRoleId}/permissions`, {
        permission_ids: Array.from(selectedPermissionIds).filter((id) => permissionMap.has(id)),
      });
      await fetchCurrentUser().catch(() => null);
      setSuccess("Role permissions updated successfully");
    } catch (err) {
      setError(err?.response?.data?.message || "Failed to update role permissions");
    } finally {
      setSaving(false);
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
              <div className="header-title-page mb-3">Role Permission Assignment</div>

              <div className="card">
                <div className="card-header">
                  <h5 className="mb-0">Role Permissions</h5>
                </div>

                <div className="card-body">
                  {error && <div className="alert alert-danger py-2">{error}</div>}
                  {success && <div className="alert alert-success py-2">{success}</div>}

                  {loading ? (
                    <div>Loading role permissions...</div>
                  ) : (
                    <>
                      <div className="mb-4" style={{ maxWidth: 380 }}>
                        <label className="form-label">Role</label>
                        <select
                          className="form-select"
                          value={selectedRoleId}
                          onChange={(e) => setSelectedRoleId(e.target.value)}
                        >
                          {roles.map((role) => (
                            <option key={role.id} value={role.id}>
                              {role.name}
                            </option>
                          ))}
                        </select>
                      </div>

                      <div className="border rounded p-3 mb-3" style={{ maxHeight: "60vh", overflowY: "auto" }}>
                        {permissions.length === 0 ? (
                          <div className="text-muted">No permissions available.</div>
                        ) : (
                          permissions.map((permission) => (
                            <PermissionNode
                              key={permission.id}
                              node={permission}
                              selectedSet={selectedPermissionIds}
                              onToggle={handleToggle}
                            />
                          ))
                        )}
                      </div>

                      <button className="btn btn-primary" onClick={savePermissions} disabled={saving || !selectedRoleId}>
                        {saving ? "Saving..." : "Save Permissions"}
                      </button>
                    </>
                  )}
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
