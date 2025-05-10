const iframe = document.createElement('iframe');
iframe.src = 'https://your-app.onrender.com/'; // Replace with your Render URL
iframe.style.width = '400px';
iframe.style.height = '500px';
iframe.style.position = 'fixed';
iframe.style.bottom = '20px';
iframe.style.right = '20px';
iframe.style.border = 'none';
document.body.appendChild(iframe);
