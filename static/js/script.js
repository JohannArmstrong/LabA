// dark theme con bootstrap
document.addEventListener("DOMContentLoaded", function () {
    const btn = document.getElementById("theme-toggle");
    const htmlTag = document.documentElement;

    const toggle = document.getElementById("theme-toggle");


    // uso de local storage para guardar el tema actual
    const savedTheme = localStorage.getItem("theme");
    if (savedTheme) {
        htmlTag.setAttribute("data-bs-theme", savedTheme);
    } else {
        htmlTag.setAttribute("data-bs-theme", "dark"); // por defecto oscuro
        localStorage.setItem("theme", "dark");
    }

    // Restaurar estado desde localStorage
    if (savedTheme === "dark") {
        toggle.checked = true;
    } else {
        toggle.checked = false;
    }


    // alternar tema mediante botón
        btn.addEventListener("click", function () {
            const currentTheme = htmlTag.getAttribute("data-bs-theme");
            const newTheme = currentTheme === "light" ? "dark" : "light";
            htmlTag.setAttribute("data-bs-theme", newTheme);
            localStorage.setItem("theme", newTheme); // guardar estado
        });
});

// función para marcar/desmarcar todos los elementos del formulario de la pág. "proyectos"
document.getElementById("toggle-all").addEventListener("click", function() {
  const checkboxes = document.querySelectorAll("input[name=columnas]");
  // sees if at least 1 is checkd
  const allChecked = Array.from(checkboxes).every(cb => cb.checked);
  checkboxes.forEach(cb => cb.checked = !allChecked);
});

//var canvas = document.getElementById("miCanvas");
//var imgData = canvas.toDataURL("image/png");
//document.getElementById("canvasExport").src = imgData;

document.addEventListener("DOMContentLoaded", function() {
  const form = document.querySelector("form");
  const exportBtn = form.querySelector("button[formaction*='estadisticas/pdf']");

  exportBtn.addEventListener("click", function() {
    const canvas = document.getElementById("graficaSedes");
    if (canvas) {
      const imgData = canvas.toDataURL("image/png");
      let hiddenInput = form.querySelector("input[name='grafica_img']");
      if (!hiddenInput) {
        hiddenInput = document.createElement("input");
        hiddenInput.type = "hidden";
        hiddenInput.name = "grafica_img";
        form.appendChild(hiddenInput);
      }
      hiddenInput.value = imgData;
    }
  });
});