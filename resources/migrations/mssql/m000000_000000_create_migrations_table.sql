CREATE TABLE dbo.migrations (
    version     NVARCHAR(255) NOT NULL,
    source      NVARCHAR(255) NOT NULL,
    apply_time  DATETIMEOFFSET(6) CONSTRAINT DF_migrations_apply_time DEFAULT SYSDATETIMEOFFSET() NOT NULL,
    CONSTRAINT PK_migrations PRIMARY KEY (version, source)
);
GO

CREATE INDEX idx_migrations_apply_time
    ON dbo.migrations (apply_time DESC);
GO

CREATE INDEX idx_migrations_source
    ON dbo.migrations (source);
GO
