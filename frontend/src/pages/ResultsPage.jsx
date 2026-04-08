import { useEffect, useState } from "react";
import { client } from "../api/client";

export default function ResultsPage() {
  const [files, setFiles] = useState([]);

  useEffect(() => {
    client.results().then((data) => setFiles(data.files || []));
  }, []);

  return (
    <section>
      <h1>Results</h1>
      <div className="grid">
        {files.map((file) => (
          <article className="card" key={file.path}>
            <h4>{file.name}</h4>
            <p>{file.kind}</p>
            {file.name.endsWith(".png") && <img src={`http://localhost:8000${file.url}`} alt={file.name} className="preview" />}
            {file.name.endsWith(".html") && (
              <iframe title={file.name} src={`http://localhost:8000${file.url}`} className="mapframe" />
            )}
            <a href={`http://localhost:8000${file.url}`} target="_blank" rel="noreferrer">Open/Download</a>
          </article>
        ))}
      </div>
    </section>
  );
}
