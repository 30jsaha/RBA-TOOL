import Swal from "sweetalert2";

export class PdfExportCancelledError extends Error {
  constructor() {
    super("PDF export cancelled");
    this.name = "PdfExportCancelledError";
  }
}

export const startPdfExportProgress = (cancelRequestedRef) => {
  const dialogPromise = Swal.fire({
    title: "Generating PDF",
    html: '<div class="dashboard-pdf-progress" role="status"><span class="dashboard-pdf-spinner" aria-hidden="true"></span><span>Preparing dashboard content…</span></div>',
    showCancelButton: true,
    showConfirmButton: false,
    cancelButtonText: "Cancel",
    allowOutsideClick: false,
    allowEscapeKey: false,
    focusCancel: true,
  });

  void dialogPromise.then((result) => {
    if (result.dismiss === Swal.DismissReason.cancel) {
      cancelRequestedRef.current = true;
    }
  });
};

export const updatePdfExportProgress = (message) => {
  if (!Swal.isVisible()) return;

  Swal.update({
    html: `<div class="dashboard-pdf-progress" role="status"><span class="dashboard-pdf-spinner" aria-hidden="true"></span><span>${message}</span></div>`,
  });
};

export const closePdfExportProgress = () => {
  if (Swal.isVisible()) Swal.close();
};

export const throwIfPdfExportCancelled = (cancelRequestedRef) => {
  if (cancelRequestedRef.current) {
    throw new PdfExportCancelledError();
  }
};

export const showPdfExportError = (error) => Swal.fire({
  icon: "error",
  title: "PDF generation failed",
  text: error?.message || "The PDF could not be generated. Please try again.",
  showCancelButton: true,
  confirmButtonText: "Retry",
  cancelButtonText: "Close",
  allowOutsideClick: false,
});
