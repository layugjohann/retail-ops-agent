# A seeded synthetic data generator instead of a public dataset

Data comes from a deterministic generator for the Client, Cobalt Home: 6 Stores, an Online Shop and about 300 SKUs. It produces daily sales and inventory Uploads, plus a catalog of planted Defects and Anomalies. Public retail datasets (UCI Online Retail II, Olist) have no store inventory and no record of which problems are real, so evals would have no exact ground truth. The generator's statistical distributions may be matched to Online Retail II so the numbers look realistic.
