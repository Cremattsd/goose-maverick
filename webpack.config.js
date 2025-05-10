const path = require('path');

module.exports = {
  entry: './src/frontend.js',
  output: {
    filename: 'frontend.bundle.js',
    path: path.resolve(__dirname, 'static'),
  },
  mode: 'production',
};
