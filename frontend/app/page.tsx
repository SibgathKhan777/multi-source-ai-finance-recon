import { Newsreader, IBM_Plex_Sans, IBM_Plex_Mono } from "next/font/google";
import Link from "next/link";
import TopNav from "@/components/TopNav";
import styles from "./problem.module.css";

const serif = Newsreader({ subsets: ["latin"], variable: "--font-serif" });
const sans = IBM_Plex_Sans({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-sans" });
const mono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-mono" });

const CASES = [
  {
    stamp: "Timezone",
    title: "Same instant, three clocks",
    data: "LDG-9601 → 18:30 IST\npay_J001 → 13:00 UTC",
    why: "Convert either one wrong and a clean match reads as a conflict that doesn't exist.",
  },
  {
    stamp: "Blank field",
    title: "Currency: (empty)",
    data: "LDG-4001 → amount 999.00\ncurrency: —",
    why: "Everything else about the row lines up. One empty cell is enough to break an exact match.",
  },
  {
    stamp: "Net settlement",
    title: "Five legs, one credit",
    data: "5 ledger rows + 5 PSP rows\n→ one bank credit, ₹5,120.50",
    why: "The bank never sees the individual transactions — only what's left after fees, netted together.",
  },
  {
    stamp: "Late arrival",
    title: "The confirmation is a week late",
    data: "transaction dated Aug 22\nbank line posts Aug 29",
    why: "File it too early and it looks missing. Match it too late and the books are already closed.",
  },
  {
    stamp: "Silent fee bug",
    title: "Short by exactly the fee",
    data: "ledger + PSP: ₹5,000.00\nbank credit: ₹4,650.00",
    why: "₹350 didn't vanish — it's the processing fee, deducted somewhere it shouldn't have been.",
  },
  {
    stamp: "Sign flip",
    title: "A sale, entered as a refund",
    data: "ledger: −₹750.00\nPSP + bank: +₹750.00",
    why: "It looks like a plausible near-miss. It's actually just wrong — and shouldn't be waved through.",
  },
];

export default function ProblemPage() {
  return (
    <div className={`${styles.page} ${serif.variable} ${sans.variable} ${mono.variable}`}>
      <TopNav active="problem" />

      <div className={styles.container}>
        <section className={styles.hero}>
          <p className={styles.eyebrow}>The problem</p>
          <h1 className={styles.headline}>Same transaction. Three different stories.</h1>
          <p className={styles.heroCaption}>
            One payment, recorded three times — in a ledger, a payment processor export, and a bank statement.
            Below is a real row from this dataset. Same amount, same day. See if you can spot what doesn&apos;t match.
          </p>

          <div className={styles.slips}>
            <div className={styles.slip}>
              <p className={styles.slipSource}>Ledger</p>
              <dl>
                <div className={styles.slipRow}>
                  <dt>txn_id</dt>
                  <dd>LDG-9002</dd>
                </div>
                <div className={`${styles.slipRow} ${styles.slipMatch}`}>
                  <dt>amount</dt>
                  <dd>1899.00</dd>
                </div>
                <div className={`${styles.slipRow} ${styles.slipFlag}`}>
                  <dt>counterparty</dt>
                  <dd>Razorpay Technologies</dd>
                </div>
              </dl>
            </div>

            <div className={styles.slip}>
              <p className={styles.slipSource}>PSP export</p>
              <dl>
                <div className={styles.slipRow}>
                  <dt>payment_id</dt>
                  <dd>pay_H002</dd>
                </div>
                <div className={`${styles.slipRow} ${styles.slipMatch}`}>
                  <dt>amt</dt>
                  <dd>1899.00</dd>
                </div>
                <div className={`${styles.slipRow} ${styles.slipFlag}`}>
                  <dt>merchant</dt>
                  <dd>RZP_MERCHANT_881</dd>
                </div>
              </dl>
            </div>

            <div className={styles.slip}>
              <p className={styles.slipSource}>Bank statement</p>
              <dl>
                <div className={styles.slipRow}>
                  <dt>ref_no</dt>
                  <dd>NEFT-9002</dd>
                </div>
                <div className={`${styles.slipRow} ${styles.slipMatch}`}>
                  <dt>value</dt>
                  <dd>1899.00</dd>
                </div>
                <div className={`${styles.slipRow} ${styles.slipFlag}`}>
                  <dt>narration</dt>
                  <dd>RAZORPAY SETTLEMENT REF9109</dd>
                </div>
              </dl>
            </div>
          </div>

          <p className={styles.heroNote}>
            Same counterparty. Three different spellings, and nothing forcing them to agree.
          </p>
        </section>

        <hr className={styles.rule} />

        <p className={styles.intro}>
          This system reconciles <b>67 transactions</b> across a ledger, a payment processor export, and a bank
          statement — three formats, three sets of IDs, no shared key. Most rows line up fine on their own. It&apos;s
          the exceptions that eat an afternoon: aliases that drift, clocks that disagree, fields left blank,
          settlements that net five legs into one credit, confirmations that show up a week late, and — quietly,
          easy to miss — the one bank credit that&apos;s short by exactly the processing fee.
        </p>

        <hr className={styles.ruleDouble} />

        <section className={styles.cases}>
          <div className={styles.sectionHead}>
            <p className={styles.eyebrow}>The junk drawer of edge cases</p>
            <h2 className={styles.sectionTitle}>Six ways the numbers stop agreeing</h2>
          </div>

          <div className={styles.grid}>
            {CASES.map((c) => (
              <article key={c.stamp} className={styles.card}>
                <span className={styles.stamp}>{c.stamp}</span>
                <h3 className={styles.cardTitle}>{c.title}</h3>
                <pre className={styles.cardData}>{c.data}</pre>
                <p className={styles.cardWhy}>{c.why}</p>
              </article>
            ))}
          </div>
        </section>

        <section className={styles.cost}>
          <p className={styles.eyebrow}>The cost</p>
          <p className={styles.costText} style={{ marginTop: "0.6rem" }}>
            Someone has to open three tabs, sort by date, and manually decide which rows are actually the same
            transaction. At 67 rows, that&apos;s an afternoon. At 67,000, it&apos;s a team — and the six cases above
            are exactly the ones that slip past a tired reviewer at 6pm. Of these 67 transactions, only{" "}
            <b>5</b> genuinely need a human to look at them. The rest can be resolved automatically, with a reason
            attached to every decision.
          </p>
          <Link href="/solution" className={styles.cta}>
            See how it gets solved →
          </Link>
        </section>
      </div>
    </div>
  );
}
