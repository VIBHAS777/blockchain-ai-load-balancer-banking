# AI-Driven Load Balancer with Blockchain-Based Decision Making in Banking System

[![Conference](https://img.shields.io/badge/Conference-10th_ICECA_2026-blue.svg)](https://iceca.in/)
[![Python](https://img.shields.io/badge/Python-3.9%2B-green.svg)](https://www.python.org/)
[![Blockchain](https://img.shields.io/badge/Architecture-Blockchain_Consensus-orange.svg)](https://en.wikipedia.org/wiki/Blockchain)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

Presented at the **10th International Conference on Electronics, Communication and Aerospace Technology (ICECA 2026)**, Coimbatore, India.

---

## 👥 Authors
- **Hima Sagar B**
- **A Vibhas Reddy** ([@VIBHAS777](https://github.com/VIBHAS777))
- **S Pavan Kumar**
- **Sreebha Bhaskaran**
- **Shinu M. Rajagopal**

---

## 🏛️ Overview
Centralized hardware load balancers in high-frequency online core banking infrastructures represent single points of failure (SPOF) and vulnerable targets for insider tampering, DNS spoofing, and DDoS saturation. 

This project implements a decentralized, AI-driven transaction routing architecture. An intelligent neural load-scoring module dynamically analyzes real-time node telemetry (CPU, active connection pools, queue depth, memory pressure). The resulting routing allocations are cryptographically validated and immutably appended to a distributed blockchain ledger, guaranteeing tamper-proof auditability and high-throughput Byzantine fault tolerance.

---

## 📁 Repository Structure
```
blockchain-ai-load-balancer-banking/
├── paper/
│   ├── AI_Driven_Load_Balancer_with_Blockchain_Decision_Making_in_Banking.pdf
│   └── Certificate_ICECA_2026.pdf
├── src/
│   ├── blockchain.py      # Cryptographic block hashing & PoW consensus ledger
│   └── load_balancer.py   # Multi-variable neural load balancing scorer
├── main.py                # Live banking burst simulation & block mining demo
├── requirements.txt
├── LICENSE
└── README.md
```

---

## 🚀 Quick Start
```bash
git clone https://github.com/VIBHAS777/blockchain-ai-load-balancer-banking.git
cd blockchain-ai-load-balancer-banking
python main.py
```

---

## 📜 Citation
```bibtex
@inproceedings{sagar2026bankingbalancer,
  title={AI-Driven Load Balancer with Blockchain-Based Decision Making in Banking System},
  author={Sagar B, Hima and Reddy, A Vibhas and Kumar, S Pavan and Bhaskaran, Sreebha and Rajagopal, Shinu M.},
  booktitle={10th International Conference on Electronics, Communication and Aerospace Technology (ICECA)},
  year={2026}
}
```
