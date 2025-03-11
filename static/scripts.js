document.addEventListener("DOMContentLoaded", function () {
    const fileInput = document.getElementById("fileInput");
    const uploadButton = document.getElementById("uploadButton");
    const extractedDataDiv = document.getElementById("extractedData");

    uploadButton.addEventListener("click", () => {
        if (fileInput.files.length > 0) {
            uploadFile(fileInput.files[0]);
        } else {
            alert("Please select a file first!");
        }
    });

    function uploadFile(file) {
        let formData = new FormData();
        formData.append("file", file);

        fetch("/upload", {
            method: "POST",
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                alert("Error: " + data.error);
            } else {
                extractedDataDiv.innerHTML = "<pre>" + JSON.stringify(data.data, null, 2) + "</pre>";
            }
        })
        .catch(error => console.error("Upload Error:", error));
    }
});
