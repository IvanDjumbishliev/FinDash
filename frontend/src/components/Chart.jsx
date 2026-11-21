import PropTypes from "prop-types";
import { Pie } from "react-chartjs-2";
import "../styles/components/Chart.css";

export default function Chart({ chartData, options }) {
  return (
    <div className="chart-container">
      <h2 className="chart-title">Expense Overview</h2>
      <div className="chart-wrapper">
        <Pie data={chartData} options={options} />
      </div>
    </div>
  );
}

Chart.propTypes = {
  chartData: PropTypes.shape({ labels: PropTypes.array, datasets: PropTypes.array.isRequired }).isRequired,
  options: PropTypes.object,
};
