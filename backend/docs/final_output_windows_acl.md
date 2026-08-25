# Final Output Windows ACL Guidance

This application now encrypts protected GST, SWT, and CIT final-output artifacts at rest by writing encrypted `*.enc` files.
Encryption protects the tax data content, but Windows filesystem ACLs should also be configured so only the application service account and administrators can read the encrypted storage directories.

## Directories to Protect

- `backend\gst\final_output`
- `backend\swt\final_output`
- `backend\cit\final_output`
- `backend\tmp\encrypted_output_staging`
- `backend\tmp\decrypted_outputs`

## Recommended Service Account

Replace `RBA_SVC` below with the Windows account that runs the backend service in UAT/production.
If the backend runs under IIS, use the IIS application-pool identity or a dedicated service account.

## Example `icacls` Commands

Run these commands from an elevated command prompt or elevated PowerShell session after deployment.

```powershell
icacls "E:\rba-tool\UAT\RBA-TOOL\backend\gst\final_output" /inheritance:r
icacls "E:\rba-tool\UAT\RBA-TOOL\backend\gst\final_output" /grant:r "RBA_SVC:(OI)(CI)M" "Administrators:(OI)(CI)F" "SYSTEM:(OI)(CI)F"
icacls "E:\rba-tool\UAT\RBA-TOOL\backend\gst\final_output" /remove:g "Users" "Authenticated Users" "Everyone"

icacls "E:\rba-tool\UAT\RBA-TOOL\backend\swt\final_output" /inheritance:r
icacls "E:\rba-tool\UAT\RBA-TOOL\backend\swt\final_output" /grant:r "RBA_SVC:(OI)(CI)M" "Administrators:(OI)(CI)F" "SYSTEM:(OI)(CI)F"
icacls "E:\rba-tool\UAT\RBA-TOOL\backend\swt\final_output" /remove:g "Users" "Authenticated Users" "Everyone"

icacls "E:\rba-tool\UAT\RBA-TOOL\backend\cit\final_output" /inheritance:r
icacls "E:\rba-tool\UAT\RBA-TOOL\backend\cit\final_output" /grant:r "RBA_SVC:(OI)(CI)M" "Administrators:(OI)(CI)F" "SYSTEM:(OI)(CI)F"
icacls "E:\rba-tool\UAT\RBA-TOOL\backend\cit\final_output" /remove:g "Users" "Authenticated Users" "Everyone"
```

## Notes

- Do not remove administrator access unless your infrastructure team has an alternate break-glass path.
- Test ACL changes in UAT before applying to production.
- The application does not claim to automatically enforce Windows ACLs at runtime, because inherited permissions and service-account models differ across environments.
- If a deployment account must create files but should not read them later, coordinate ownership and ACL inheritance with your infrastructure team before rollout.
