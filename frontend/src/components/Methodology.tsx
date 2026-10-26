/** Methodology — static formulas; the loss factors (α, availability,
 * electrical, wake, U) come live from /api/metrics (plan phase 4). Hub and
 * mast heights are already shown in the header subtitle. */
import type { Metrics } from "../api";
import { asNum, asPercent } from "../format";

export function Methodology({ metrics }: { metrics: Metrics }) {
  const { site } = metrics;

  return (
    <>
      <p className="methodology">
        Stündliche Messwerte des Messmasts (nur Qualität <code>ok</code>) werden mit dem
        Windgradienten auf Nabenhöhe umgerechnet:{" "}
        <code>
          v<sub>Nabe</sub> = v<sub>Mess</sub> · (h<sub>Nabe</sub> / h<sub>Mess</sub>)<sup>α</sup>
        </code>
        , über die Leistungskennlinie in Energie je Stunde überführt (kW · 1 h → kWh) und über die
        letzten 12 Monate summiert → AEP brutto. Die Verluste ergeben die Ertragskette: AEP netto =
        AEP brutto · (1 − Verfügbarkeit) · (1 − elektrisch) · (1 − Abschattung); P50 = AEP netto;
        und als konservative Größe P90 = P50 · (1 − 1,282 · U).
      </p>
      <table className="history factors">
        <thead>
          <tr>
            <th>Faktor</th>
            <th>Wert</th>
            <th>Quelle</th>
          </tr>
        </thead>
        <tbody>
          <Factor
            label="Windgradient (Höhenexponent) α"
            value={pv(site?.shear_exponent)}
            source={site?.name}
          />
          <Factor
            label="Verfügbarkeitsverlust"
            value={pv(site?.availability_loss, true)}
            source={site?.name}
          />
          <Factor
            label="elektrische Verluste"
            value={pv(site?.electrical_loss, true)}
            source={site?.name}
          />
          <Factor
            label="Abschattungsverlust"
            value={pv(site?.wake_loss, true)}
            source={site?.name}
          />
          <Factor label="Unsicherheit U" value={pv(site?.uncertainty, true)} source={site?.name} />
        </tbody>
      </table>
    </>
  );
}

function Factor({
  label,
  value,
  source,
}: {
  label: string;
  value: string;
  source: string | undefined;
}) {
  return (
    <tr>
      <td>{label}</td>
      <td>{value}</td>
      <td>{source ?? "–"}</td>
    </tr>
  );
}

const pv = (value: number | undefined, percent = false): string => {
  if (value == null) return "–";
  return percent ? `${asPercent(value, 1)} %` : asNum(value);
};
